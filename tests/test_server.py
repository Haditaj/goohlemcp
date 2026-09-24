import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from conftest import call
from goohle_mcp.app import mcp


async def test_tool_catalogue_is_consistent():
    tools = await mcp.list_tools()
    names = [t.name for t in tools]
    assert len(names) == len(set(names))
    for tool in tools:
        assert tool.name.split("_")[0] in {"ga4", "gsc", "gtm"}
        assert tool.description
        props = tool.input_schema.get("properties", {})
        if tool.annotations.read_only_hint:
            assert "dry_run" not in props, tool.name
        else:
            assert "dry_run" in props, f"{tool.name} changes data but has no dry_run"


async def test_prompts_are_registered():
    assert {p.name for p in await mcp.list_prompts()} == {"tracking_audit", "seo_review", "weekly_report"}


def _error_body(status, message, reason):
    return {"error": {"code": status, "message": message, "details": [{"reason": reason}]}}


@pytest.mark.parametrize(
    ("status", "reason", "message", "hint"),
    [
        (403, "SERVICE_DISABLED", "Google Analytics Data API has not been used", "Google Analytics Data API is not enabled"),
        (403, "ACCESS_TOKEN_SCOPE_INSUFFICIENT", "Request had insufficient authentication scopes.", "without --read-only"),
        (403, "PERMISSION_DENIED", "User does not have sufficient permissions", "no access"),
        (404, "NOT_FOUND", "Property not found", "Not found"),
        (401, "UNAUTHENTICATED", "Invalid credentials", "goohle-mcp auth"),
    ],
)
async def test_api_errors_come_with_next_steps(http, status, reason, message, hint):
    http.queue(_error_body(status, message, reason), status=status)
    with pytest.raises(ToolError) as info:
        await call("ga4_run_report", property_id="123", metrics=["sessions"])
    text = str(info.value)
    assert f"Google API error {status}" in text
    assert message in text
    assert hint in text


async def test_failed_write_is_audited(http, monkeypatch, tmp_path):
    monkeypatch.setenv("GOOHLE_MCP_MODE", "write")
    http.queue(_error_body(409, "Fingerprint mismatch", "ABORTED"), status=409)
    with pytest.raises(ToolError, match="Conflict"):
        await call("gtm_delete_entity", path="accounts/1/containers/2/workspaces/3/tags/4")
    entry = json.loads((tmp_path / "audit.jsonl").read_text().splitlines()[-1])
    assert entry["status"] == "error" and entry["method"] == "DELETE"
