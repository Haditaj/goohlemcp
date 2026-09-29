"""Google Sheets: read a sheet and append exported CSV rows to a tab."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from goohle_mcp import config
from goohle_mcp.app import CHANGE, CREATE, READ, mcp
from goohle_mcp.google_api import execute, mutate, service
from goohle_mcp.tools.common import DryRun

SpreadsheetId = Annotated[
    str, Field(description="Spreadsheet ID or its full docs.google.com/spreadsheets/d/<id>/... URL.")
]
Tab = Annotated[str, Field(description="Tab (sheet) name exactly as shown, e.g. 'auto_ga4'.")]

_CHUNK = 5000  # rows per append request


def _sheets() -> Any:
    return service("sheets", "v4")


def spreadsheet_id(value: str) -> str:
    match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", value)
    sid = match.group(1) if match else value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,}", sid):
        raise ToolError(f"'{value}' is not a spreadsheet ID or URL.")
    config.require_allowed("sheets", sid)
    return sid


def _a1(tab: str, cells: str = "") -> str:
    quoted = "'" + tab.replace("'", "''") + "'"
    return f"{quoted}!{cells}" if cells else quoted


@mcp.tool(name="sheets_get_info", title="List spreadsheet tabs", annotations=READ)
async def sheets_get_info(spreadsheet: SpreadsheetId) -> dict[str, Any]:
    """Returns the spreadsheet title and its tabs with size, plus each tab's header row."""
    sid = spreadsheet_id(spreadsheet)
    meta = await execute(
        _sheets().spreadsheets().get(spreadsheetId=sid, fields="properties.title,sheets.properties")
    )
    tabs = [s["properties"] for s in meta.get("sheets", [])]
    headers: dict[str, list[str]] = {}
    if tabs:
        ranges = [_a1(t["title"], "1:1") for t in tabs]
        got = await execute(_sheets().spreadsheets().values().batchGet(spreadsheetId=sid, ranges=ranges))
        for tab, vr in zip(tabs, got.get("valueRanges", [])):
            headers[tab["title"]] = (vr.get("values") or [[]])[0]
    return {
        "title": meta.get("properties", {}).get("title"),
        "tabs": [
            {
                "title": t["title"],
                "rows": t.get("gridProperties", {}).get("rowCount"),
                "columns": t.get("gridProperties", {}).get("columnCount"),
                "header": headers.get(t["title"], []),
            }
            for t in tabs
        ],
    }


@mcp.tool(name="sheets_read_range", title="Read spreadsheet cells", annotations=READ)
async def sheets_read_range(
    spreadsheet: SpreadsheetId,
    range: Annotated[str, Field(description="A1 range, e.g. \"'auto_ga4'!A1:J50\" or just a tab name.")],
    max_rows: Annotated[int, Field(ge=1, le=5000)] = 200,
    render: Annotated[
        Literal["FORMATTED_VALUE", "UNFORMATTED_VALUE", "FORMULA"],
        Field(description="FORMATTED_VALUE = as displayed; FORMULA = formulas instead of results; "
                          "UNFORMATTED_VALUE = raw values (real dates come back as serial numbers)."),
    ] = "FORMATTED_VALUE",
) -> dict[str, Any]:
    """Reads cell values. Use it to find the last date already in a tab or to inspect formulas."""
    sid = spreadsheet_id(spreadsheet)
    got = await execute(
        _sheets().spreadsheets().values().get(spreadsheetId=sid, range=range, valueRenderOption=render)
    )
    values = got.get("values", [])
    return {"range": got.get("range"), "row_count": len(values), "values": values[:max_rows],
            "truncated": len(values) > max_rows}


def _col(n: int) -> str:
    """1 -> A, 27 -> AA."""
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


@mcp.tool(name="sheets_append_csv", title="Append CSV rows to a tab", annotations=CREATE)
async def sheets_append_csv(
    spreadsheet: SpreadsheetId,
    tab: Tab,
    csv_path: Annotated[str, Field(description="Local CSV file with a header row, e.g. one written by save_csv.")],
    value_input: Annotated[
        Literal["USER_ENTERED", "RAW"],
        Field(description="USER_ENTERED parses numbers and dates like typing them; RAW stores text as-is."),
    ] = "USER_ENTERED",
    header_row: Annotated[
        int, Field(ge=1, le=100, description="Row number of the tab's column-title row (1 unless the tab has notes above it).")
    ] = 1,
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Writes every data row of a local CSV into the empty rows right below a tab's data.

    The CSV header must match the tab's header row (`header_row`) exactly (same names,
    same order); otherwise nothing is written. If that row is empty, the CSV header is
    written there first. The first empty row is found from column A. Rows are written
    into existing empty cells (never inserted), so formulas elsewhere that point at this
    tab keep their ranges; rows are added only at the bottom of the grid when it is too
    short. If any target cell already holds a value or formula, nothing is written.
    Rows never pass through the conversation, so large exports are fine.
    """
    sid = spreadsheet_id(spreadsheet)
    path = Path(csv_path).expanduser()
    if not path.is_file():
        raise ToolError(f"CSV file not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        raise ToolError("The CSV file is empty.")
    header, data = rows[0], rows[1:]
    last_col = _col(len(header))

    got = await execute(_sheets().spreadsheets().values().get(spreadsheetId=sid, range=_a1(tab, f"{header_row}:{header_row}")))
    existing = (got.get("values") or [[]])[0]
    if existing and [h.strip() for h in existing] != [h.strip() for h in header]:
        raise ToolError(
            f"Column mismatch, nothing written.\nTab '{tab}' row {header_row}: {existing}\nCSV header:       {header}\n"
            "Reorder or rename the CSV columns to match the tab exactly."
        )
    if not existing:
        data = [header] + data
        first = header_row
    else:
        col_a = await execute(
            _sheets().spreadsheets().values().get(spreadsheetId=sid, range=_a1(tab, f"A{header_row + 1}:A"))
        )
        first = header_row + 1 + len(col_a.get("values", []))
    if not data:
        return {"appended_rows": 0, "note": "The CSV has no data rows."}
    last = first + len(data) - 1
    target = f"A{first}:{last_col}{last}"

    meta = await execute(
        _sheets().spreadsheets().get(spreadsheetId=sid, fields="sheets.properties(sheetId,title,gridProperties)")
    )
    props = next((s["properties"] for s in meta.get("sheets", []) if s["properties"]["title"] == tab), None)
    if props is None:
        raise ToolError(f"Tab '{tab}' not found in this spreadsheet.")
    grid_rows = props.get("gridProperties", {}).get("rowCount", 0)
    extra_rows = max(0, last - grid_rows)

    if first <= grid_rows:
        check_end = min(last, grid_rows)
        occupied = await execute(
            _sheets().spreadsheets().values().get(
                spreadsheetId=sid, range=_a1(tab, f"A{first}:{last_col}{check_end}"), valueRenderOption="FORMULA"
            )
        )
        for offset, row in enumerate(occupied.get("values", [])):
            if any(str(cell).strip() for cell in row):
                raise ToolError(
                    f"Nothing written: row {first + offset} of '{tab}' already has content in {target} "
                    f"(column A is empty there but other columns are not): {row}. "
                    "Clear those cells or move the data, then try again."
                )

    if dry_run:
        await mutate(
            "sheets_append_csv", _sheets().spreadsheets().values().update(
                spreadsheetId=sid, range=_a1(tab, target), valueInputOption=value_input, body={"values": []}
            ),
            dry_run=True,
            summary={"method": "PUT", "uri": f"sheets:{sid}/{tab}!{target}",
                     "body": {"rows": len(data), "grid_rows_added": extra_rows, "csv": str(path)}},
        )
        return {
            "dry_run": True,
            "tab": tab,
            "header_ok": True,
            "writes_header_first": not existing,
            "target_range": target,
            "grid_rows_added_at_bottom": extra_rows,
            "rows_to_append": len(data),
            "first_rows": data[:3],
            "last_row": data[-1],
        }

    if extra_rows:
        grow = _sheets().spreadsheets().batchUpdate(
            spreadsheetId=sid,
            body={"requests": [{"appendDimension": {"sheetId": props["sheetId"], "dimension": "ROWS", "length": extra_rows}}]},
        )
        await mutate("sheets_append_csv", grow, dry_run=False,
                     summary={"method": "POST", "uri": f"sheets:{sid}/{tab}:appendRows", "body": {"rows": extra_rows}})

    total = 0
    for start in range(0, len(data), _CHUNK):
        chunk = data[start : start + _CHUNK]
        row0 = first + start
        cells = f"A{row0}:{last_col}{row0 + len(chunk) - 1}"
        request = (
            _sheets()
            .spreadsheets()
            .values()
            .update(spreadsheetId=sid, range=_a1(tab, cells), valueInputOption=value_input, body={"values": chunk})
        )
        summary = {
            "method": "PUT",
            "uri": f"sheets:{sid}/{tab}!{cells}",
            "body": {"rows": len(chunk), "first_row": chunk[0], "last_row": chunk[-1], "csv": str(path)},
        }
        await mutate("sheets_append_csv", request, dry_run=False, summary=summary)
        total += len(chunk)
    return {"appended_rows": total, "updated_range": f"{tab}!{target}", "grid_rows_added_at_bottom": extra_rows}


@mcp.tool(name="sheets_write_range", title="Overwrite spreadsheet cells", annotations=CHANGE)
async def sheets_write_range(
    spreadsheet: SpreadsheetId,
    range: Annotated[str, Field(description="A1 range whose top-left cell is written first, e.g. \"'notes'!B2\".")],
    values: Annotated[list[list[Any]], Field(description="Rows of cell values, e.g. [['2026-09-25', 12]].")],
    value_input: Literal["USER_ENTERED", "RAW"] = "USER_ENTERED",
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Overwrites a small block of cells. For adding exported rows use sheets_append_csv."""
    sid = spreadsheet_id(spreadsheet)
    request = (
        _sheets()
        .spreadsheets()
        .values()
        .update(spreadsheetId=sid, range=range, valueInputOption=value_input, body={"values": values})
    )
    return await mutate("sheets_write_range", request, dry_run=dry_run)
