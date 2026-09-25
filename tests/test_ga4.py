import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from conftest import call


async def test_run_report_builds_request_and_flattens_rows(http):
    http.queue(
        {
            "dimensionHeaders": [{"name": "sessionDefaultChannelGroup"}],
            "metricHeaders": [
                {"name": "sessions", "type": "TYPE_INTEGER"},
                {"name": "engagementRate", "type": "TYPE_FLOAT"},
            ],
            "rows": [
                {"dimensionValues": [{"value": "Organic Search"}], "metricValues": [{"value": "120"}, {"value": "0.61"}]},
                {"dimensionValues": [{"value": "Direct"}], "metricValues": [{"value": "80"}, {"value": "0.4"}]},
            ],
            "rowCount": 5,
            "metadata": {"currencyCode": "USD", "timeZone": "Asia/Tehran"},
        }
    )

    result = await call(
        "ga4_run_report",
        property_id="properties/123",
        metrics=["sessions", "engagementRate"],
        dimensions=["sessionDefaultChannelGroup"],
        order_by=["-sessions"],
        limit=2,
    )

    sent = http.requests[0]
    assert sent["method"] == "POST"
    assert "analyticsdata.googleapis.com/v1beta/properties/123:runReport" in sent["uri"]
    assert sent["body"]["orderBys"] == [{"metric": {"metricName": "sessions"}, "desc": True}]
    assert sent["body"]["dateRanges"] == [{"startDate": "28daysAgo", "endDate": "yesterday", "name": "current"}]
    assert result["rows"][0] == {"sessionDefaultChannelGroup": "Organic Search", "sessions": 120, "engagementRate": 0.61}
    assert result["next_offset"] == 2
    assert result["metadata"]["time_zone"] == "Asia/Tehran"


async def test_run_report_with_comparison_range(http):
    http.queue({"rows": []})
    await call(
        "ga4_run_report",
        property_id="123",
        metrics=["sessions"],
        start_date="7daysAgo",
        end_date="yesterday",
        compare_start_date="14daysAgo",
        compare_end_date="8daysAgo",
    )
    ranges = http.requests[0]["body"]["dateRanges"]
    assert [r["name"] for r in ranges] == ["current", "previous"]


@pytest.mark.parametrize("bad", ["G-ABC123", "abc", "properties/x"])
async def test_measurement_id_is_rejected_with_hint(http, bad):
    with pytest.raises(ToolError, match="not a GA4 property ID"):
        await call("ga4_get_property", property_id=bad)
    assert http.requests == []


async def test_order_by_unknown_field(http):
    with pytest.raises(ToolError, match="order_by"):
        await call("ga4_run_report", property_id="1", metrics=["sessions"], order_by=["-users"])


async def test_writes_are_blocked_in_read_mode(http):
    with pytest.raises(ToolError, match="GOOHLE_MCP_MODE=write"):
        await call(
            "ga4_create_custom_dimension", property_id="123", parameter_name="author", display_name="Author"
        )
    assert http.requests == []


async def test_dry_run_works_in_read_mode_and_is_audited(http, tmp_path):
    result = await call(
        "ga4_create_custom_dimension",
        property_id="123",
        parameter_name="author",
        display_name="Author",
        scope="EVENT",
        dry_run=True,
    )
    assert http.requests == []
    assert result["dry_run"] is True
    assert result["would_send"]["method"] == "POST"
    assert result["would_send"]["uri"].endswith("/v1beta/properties/123/customDimensions")
    assert result["would_send"]["body"] == {"parameterName": "author", "displayName": "Author", "scope": "EVENT"}
    log = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert log[0]["tool"] == "ga4_create_custom_dimension" and log[0]["status"] == "dry_run"


async def test_patch_sends_update_mask_in_write_mode(http, monkeypatch, tmp_path):
    monkeypatch.setenv("GOOHLE_MCP_MODE", "write")
    http.queue({"name": "properties/123/customDimensions/9", "displayName": "Writer"})
    result = await call(
        "ga4_update_custom_dimension", name="properties/123/customDimensions/9", display_name="Writer"
    )
    sent = http.requests[0]
    assert sent["method"] == "PATCH"
    assert "updateMask=displayName" in sent["uri"]
    assert sent["body"] == {"displayName": "Writer"}
    assert result["displayName"] == "Writer"
    assert '"status": "ok"' in (tmp_path / "audit.jsonl").read_text()


async def test_update_without_fields_is_rejected(http, monkeypatch):
    monkeypatch.setenv("GOOHLE_MCP_MODE", "write")
    with pytest.raises(ToolError, match="Nothing to update"):
        await call("ga4_update_property", property_id="123")


async def test_annotation_uses_date_parts(http):
    result = await call(
        "ga4_create_annotation", property_id="123", title="GTM v12", date="2026-09-01", dry_run=True
    )
    body = result["would_send"]["body"]
    assert body["annotationDate"] == {"year": 2026, "month": 9, "day": 1}
    assert "v1alpha/properties/123/reportingDataAnnotations" in result["would_send"]["uri"]


async def test_key_event_value_requires_currency(http):
    with pytest.raises(ToolError, match="default_currency"):
        await call("ga4_create_key_event", property_id="1", event_name="purchase", default_value=10, dry_run=True)


async def test_create_property_and_web_stream_requests(http):
    prop = await call("ga4_create_property", account_id="404", display_name="example.com", time_zone="Asia/Tehran", dry_run=True)
    assert prop["would_send"]["uri"].endswith("/v1beta/properties")
    assert prop["would_send"]["body"]["parent"] == "accounts/404"
    stream = await call("ga4_create_web_stream", property_id="55", default_uri="https://example.com", display_name="web", dry_run=True)
    assert stream["would_send"]["body"]["webStreamData"] == {"defaultUri": "https://example.com"}


async def test_run_report_save_csv(http, tmp_path):
    def page(n, total):
        return {
            "dimensionHeaders": [{"name": "date"}],
            "metricHeaders": [{"name": "sessions", "type": "TYPE_INTEGER"}],
            "rows": [{"dimensionValues": [{"value": "20260901"}], "metricValues": [{"value": "5"}]}] * n,
            "rowCount": total,
        }
    http.queue(page(10000, 10002))
    http.queue(page(2, 10002))
    out = tmp_path / "ga4.csv"
    result = await call("ga4_run_report", property_id="1", metrics=["sessions"], dimensions=["date"], save_csv=str(out))
    assert result["row_count"] == 10002
    assert http.requests[1]["body"]["offset"] == 10000
    assert out.read_text().splitlines()[:2] == ["date,sessions", "20260901,5"]
