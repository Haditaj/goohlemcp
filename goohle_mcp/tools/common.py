"""Small helpers shared by the tool modules."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Annotated, Any

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

DryRun = Annotated[
    bool,
    Field(
        description=(
            "If true, nothing is changed: the exact API request is returned for review. "
            "Works in every mode."
        )
    ),
]

_RELATIVE_DATE = re.compile(r"^(\d+)daysAgo$")


def resolve_date(value: str, *, today: date | None = None) -> str:
    """Accepts YYYY-MM-DD, 'today', 'yesterday' or 'NdaysAgo'; returns YYYY-MM-DD."""
    today = today or date.today()
    text = value.strip()
    if text == "today":
        return today.isoformat()
    if text == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    match = _RELATIVE_DATE.match(text)
    if match:
        return (today - timedelta(days=int(match.group(1)))).isoformat()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise ToolError(
            f"Invalid date '{value}'. Use YYYY-MM-DD, 'today', 'yesterday' or 'NdaysAgo'."
        ) from None


def changed_fields(**fields: Any) -> tuple[dict[str, Any], str]:
    """Builds a PATCH body and update mask from the arguments that were given."""
    body = {key: value for key, value in fields.items() if value is not None}
    if not body:
        raise ToolError("Nothing to update: pass at least one field to change.")
    return body, ",".join(body)


def drop_empty(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value not in (None, [], {}, "")}


SaveCsv = Annotated[
    str | None,
    Field(
        description=(
            "Write ALL rows (every page) to this CSV file instead of returning them, and return "
            "only a summary. Use for large exports, e.g. '/Users/me/moa/auto_ga4.csv'."
        )
    ),
]


def write_csv(path: str, rows: list[dict[str, Any]], columns: list[str]) -> dict[str, Any]:
    """Writes rows to a UTF-8 CSV and returns a short summary for the model."""
    import csv
    from pathlib import Path

    target = Path(path).expanduser().resolve()
    if target.suffix.lower() != ".csv":
        raise ToolError("save_csv must be a path ending in .csv.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return {"saved_to": str(target), "row_count": len(rows), "columns": columns, "preview": rows[:5]}
