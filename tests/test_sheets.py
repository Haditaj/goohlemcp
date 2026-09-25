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


async def test_append_checks_header_and_appends(http, monkeypatch, csv_file):
    monkeypatch.setenv("GOOHLE_MCP_MODE", "write")
    http.queue({"values": [["date", "sessions"]]})
    http.queue({"updates": {"updatedRange": "auto_ga4!A10:B11"}})
    result = await call("sheets_append_csv", spreadsheet=URL, tab="auto_ga4", csv_path=str(csv_file))
    append = http.requests[1]
    assert f"/v4/spreadsheets/{SID}/values/%27auto_ga4%27%21A1:append" in append["uri"]
    assert "insertDataOption=INSERT_ROWS" in append["uri"]
    assert append["body"] == {"values": [["2026-09-01", "5"], ["2026-09-02", "7"]]}
    assert result == {"appended_rows": 2, "updated_range": "auto_ga4!A10:B11"}


async def test_append_refuses_column_mismatch(http, monkeypatch, csv_file):
    monkeypatch.setenv("GOOHLE_MCP_MODE", "write")
    http.queue({"values": [["date", "source_medium", "sessions"]]})
    with pytest.raises(ToolError, match="Column mismatch"):
        await call("sheets_append_csv", spreadsheet=SID, tab="auto_ga4", csv_path=str(csv_file))
    assert len(http.requests) == 1


async def test_append_dry_run_writes_header_to_empty_tab(http, csv_file, tmp_path):
    http.queue({})
    result = await call("sheets_append_csv", spreadsheet=SID, tab="auto_ga4", csv_path=str(csv_file), dry_run=True)
    assert result["writes_header_first"] is True
    assert result["rows_to_append"] == 3
    assert len(http.requests) == 1
    assert '"rows": 3' in (tmp_path / "audit.jsonl").read_text()


async def test_sheet_allowlist(http, monkeypatch):
    monkeypatch.setenv("GOOHLE_MCP_SHEETS", SID)
    with pytest.raises(ToolError, match="outside the resources"):
        await call("sheets_read_range", spreadsheet="1abcdefghijklmnopqrstuvwxyz0123", range="A1")
    http.queue({"range": "notes!A1", "values": [["x"]]})
    result = await call("sheets_read_range", spreadsheet=URL, range="notes!A1")
    assert result["values"] == [["x"]]
