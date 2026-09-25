from datetime import date

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from conftest import call
from goohle_mcp.tools.common import resolve_date


def test_resolve_date():
    today = date(2026, 9, 24)
    assert resolve_date("today", today=today) == "2026-09-24"
    assert resolve_date("yesterday", today=today) == "2026-09-23"
    assert resolve_date("30daysAgo", today=today) == "2026-08-25"
    assert resolve_date("2026-01-05", today=today) == "2026-01-05"
    with pytest.raises(ToolError):
        resolve_date("last week", today=today)


async def test_search_analytics_maps_filters_and_rows(http):
    http.queue(
        {
            "rows": [{"keys": ["seo tools", "https://example.com/a"], "clicks": 10, "impressions": 200, "ctr": 0.05, "position": 4.26}],
            "responseAggregationType": "byPage",
        }
    )
    result = await call(
        "gsc_search_analytics",
        site_url="sc-domain:example.com",
        dimensions=["query", "page"],
        start_date="2026-08-01",
        end_date="2026-08-31",
        filters=[{"dimension": "page", "operator": "contains", "expression": "/blog/"}],
        row_limit=1,
    )
    sent = http.requests[0]
    assert "/webmasters/v3/sites/sc-domain%3Aexample.com/searchAnalytics/query" in sent["uri"]
    assert sent["body"]["dimensionFilterGroups"] == [
        {"groupType": "and", "filters": [{"dimension": "page", "operator": "contains", "expression": "/blog/"}]}
    ]
    assert result["rows"] == [
        {"query": "seo tools", "page": "https://example.com/a", "clicks": 10, "impressions": 200, "ctr": 0.05, "position": 4.3}
    ]
    assert result["next_start_row"] == 1


async def test_submit_sitemap_in_write_mode(http, monkeypatch):
    monkeypatch.setenv("GOOHLE_MCP_MODE", "write")
    http.queue(None)
    result = await call(
        "gsc_submit_sitemap", site_url="https://example.com/", sitemap_url="https://example.com/sitemap.xml"
    )
    sent = http.requests[0]
    assert sent["method"] == "PUT"
    assert "sites/https%3A%2F%2Fexample.com%2F/sitemaps/https%3A%2F%2Fexample.com%2Fsitemap.xml" in sent["uri"]
    assert result == {"ok": True}


async def test_inspect_url_returns_inspection_result(http):
    http.queue({"inspectionResult": {"indexStatusResult": {"verdict": "PASS"}}})
    result = await call("gsc_inspect_url", site_url="https://example.com/", url="https://example.com/a")
    assert result == {"indexStatusResult": {"verdict": "PASS"}}
    assert http.requests[0]["body"]["inspectionUrl"] == "https://example.com/a"


async def test_save_csv_pages_through_everything(http, tmp_path):
    first = [{"keys": [f"q{i}"], "clicks": 1, "impressions": 2, "ctr": 0.5, "position": 3} for i in range(25000)]
    http.queue({"rows": first})
    http.queue({"rows": [{"keys": ["last"], "clicks": 9, "impressions": 9, "ctr": 1, "position": 1}]})
    out = tmp_path / "gsc.csv"
    result = await call("gsc_search_analytics", site_url="sc-domain:example.com", dimensions=["query"], save_csv=str(out))
    assert result["row_count"] == 25001
    assert http.requests[1]["body"]["startRow"] == 25000
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "query,clicks,impressions,ctr,position"
    assert lines[-1] == "last,9,9,1,1"
    assert "rows" not in result
