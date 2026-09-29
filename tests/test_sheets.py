from urllib.parse import unquote

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from conftest import call

SID = "1QKiOXiWMpzgmm8Gb82UXiHzygXk9lDkWkQBS-fkxg00"
URL = f"https://docs.google.com/spreadsheets/d/{SID}/edit?usp=sharing"


@pytest.fixture
def csv_file(tmp_path):
    path = tmp_path / "auto_ga4.csv"
    path.write_text("date,sessions\n2026-09-01,5\n2026-09-02,7\n", encoding="utf-8")
    return path


def _meta(rows=1000):
    return {"sheets": [{"properties": {"sheetId": 7, "title": "auto_ga4", "gridProperties": {"rowCount": rows}}}]}


async def test_append_writes_into_empty_rows_without_inserting(http, monkeypatch, csv_file):
    monkeypatch.setenv("GOOHLE_MCP_MODE", "write")
    http.queue({"values": [["date", "sessions"]]})           # header row
    http.queue({"values": [["2026-08-30"], ["2026-08-31"]]})  # column A below header
    http.queue(_meta())                                      # grid size
    http.queue({})                                           # target cells are empty
    http.queue({"updatedRange": "auto_ga4!A4:B5"})
    result = await call("sheets_append_csv", spreadsheet=URL, tab="auto_ga4", csv_path=str(csv_file))
    assert "'auto_ga4'!A2:A" in unquote(http.requests[1]["uri"])
    assert "valueRenderOption=FORMULA" in http.requests[3]["uri"]
    write = http.requests[4]
    assert write["method"] == "PUT" and "'auto_ga4'!A4:B5" in unquote(write["uri"])
    assert ":append" not in write["uri"] and "INSERT_ROWS" not in write["uri"]
    assert write["body"] == {"values": [["2026-09-01", "5"], ["2026-09-02", "7"]]}
    assert result == {"appended_rows": 2, "updated_range": "auto_ga4!A4:B5", "grid_rows_added_at_bottom": 0}


async def test_append_refuses_to_overwrite_formulas(http, monkeypatch, csv_file):
    monkeypatch.setenv("GOOHLE_MCP_MODE", "write")
    http.queue({"values": [["date", "sessions"]]})
    http.queue({})
    http.queue(_meta())
    http.queue({"values": [["", "=B1*2"]]})
    with pytest.raises(ToolError, match="already has content"):
        await call("sheets_append_csv", spreadsheet=SID, tab="auto_ga4", csv_path=str(csv_file))
    assert all(r["method"] == "GET" for r in http.requests)


async def test_append_grows_grid_at_bottom_only(http, monkeypatch, csv_file):
    monkeypatch.setenv("GOOHLE_MCP_MODE", "write")
    http.queue({"values": [["date", "sessions"]]})
    http.queue({"values": [["x"]] * 3})   # rows 2-4 filled, next free row is 5
    http.queue(_meta(rows=5))
    http.queue({})
    http.queue({})                        # appendDimension
    http.queue({})
    result = await call("sheets_append_csv", spreadsheet=SID, tab="auto_ga4", csv_path=str(csv_file))
    grow = http.requests[4]
    assert grow["body"]["requests"][0]["appendDimension"] == {"sheetId": 7, "dimension": "ROWS", "length": 1}
    assert "'auto_ga4'!A5:B6" in unquote(http.requests[5]["uri"])
    assert result["grid_rows_added_at_bottom"] == 1


async def test_append_refuses_column_mismatch(http, monkeypatch, csv_file):
    monkeypatch.setenv("GOOHLE_MCP_MODE", "write")
    http.queue({"values": [["date", "source_medium", "sessions"]]})
    with pytest.raises(ToolError, match="Column mismatch"):
        await call("sheets_append_csv", spreadsheet=SID, tab="auto_ga4", csv_path=str(csv_file))
    assert len(http.requests) == 1


async def test_append_dry_run_writes_header_to_empty_tab(http, csv_file, tmp_path):
    http.queue({})
    http.queue(_meta())
    http.queue({})
    result = await call("sheets_append_csv", spreadsheet=SID, tab="auto_ga4", csv_path=str(csv_file), dry_run=True)
    assert result["writes_header_first"] is True
    assert result["rows_to_append"] == 3
    assert result["target_range"] == "A1:B3"
    assert all(r["method"] == "GET" for r in http.requests)
    assert '"rows": 3' in (tmp_path / "audit.jsonl").read_text()


async def test_sheet_allowlist(http, monkeypatch):
    monkeypatch.setenv("GOOHLE_MCP_SHEETS", SID)
    with pytest.raises(ToolError, match="outside the resources"):
        await call("sheets_read_range", spreadsheet="1abcdefghijklmnopqrstuvwxyz0123", range="A1")
    http.queue({"range": "notes!A1", "values": [["x"]]})
    result = await call("sheets_read_range", spreadsheet=URL, range="notes!A1")
    assert result["values"] == [["x"]]


async def test_append_uses_header_row(http, monkeypatch, csv_file):
    monkeypatch.setenv("GOOHLE_MCP_MODE", "write")
    http.queue({"values": [["date", "sessions"]]})
    http.queue({})
    http.queue(_meta())
    http.queue({})
    http.queue({})
    await call("sheets_append_csv", spreadsheet=SID, tab="auto_ga4", csv_path=str(csv_file), header_row=4)
    assert "'auto_ga4'!4:4" in unquote(http.requests[0]["uri"])
    assert "'auto_ga4'!A5:A" in unquote(http.requests[1]["uri"])
    assert "'auto_ga4'!A5:B6" in unquote(http.requests[4]["uri"])


async def test_read_range_can_return_formulas(http):
    http.queue({"range": "calc_qa!A5", "values": [["=A4+1"]]})
    result = await call("sheets_read_range", spreadsheet=SID, range="calc_qa!A5", render="FORMULA")
    assert "valueRenderOption=FORMULA" in http.requests[0]["uri"]
    assert result["values"] == [["=A4+1"]]
