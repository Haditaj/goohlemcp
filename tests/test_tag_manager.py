import pytest
from mcp.server.mcpserver.exceptions import ToolError

from conftest import call

WS = "accounts/1/containers/2/workspaces/3"


async def test_list_entities_summarises(http):
    http.queue(
        {
            "tag": [
                {"path": f"{WS}/tags/7", "name": "GA4 - purchase", "type": "gaawe", "firingTriggerId": ["12"], "fingerprint": "f1", "parameter": [{"key": "eventName"}]}
            ],
            "nextPageToken": "p2",
        }
    )
    http.queue({"tag": [{"path": f"{WS}/tags/8", "name": "Google tag", "type": "googtag"}]})
    result = await call("gtm_list_entities", workspace_path=WS, entity_type="tags")
    assert [t["name"] for t in result["tags"]] == ["GA4 - purchase", "Google tag"]
    assert "parameter" not in result["tags"][0]
    assert "pageToken=p2" in http.requests[1]["uri"]


async def test_update_entity_merges_and_sends_fingerprint(http, monkeypatch):
    monkeypatch.setenv("GOOHLE_MCP_MODE", "write")
    current = {"path": f"{WS}/tags/7", "name": "GA4 - purchase", "type": "gaawe", "paused": False, "fingerprint": "abc"}
    http.queue(current)
    http.queue({**current, "paused": True, "fingerprint": "def"})
    result = await call("gtm_update_entity", path=f"{WS}/tags/7", changes={"paused": True})
    get, put = http.requests
    assert get["method"] == "GET"
    assert put["method"] == "PUT"
    assert "fingerprint=abc" in put["uri"]
    assert put["body"]["paused"] is True and put["body"]["name"] == "GA4 - purchase"
    assert result["fingerprint"] == "def"


async def test_publish_needs_publish_mode(http, monkeypatch):
    monkeypatch.setenv("GOOHLE_MCP_MODE", "write")
    with pytest.raises(ToolError, match="GOOHLE_MCP_MODE=publish"):
        await call("gtm_publish_version", version_path="accounts/1/containers/2/versions/15")
    assert http.requests == []

    monkeypatch.setenv("GOOHLE_MCP_MODE", "publish")
    http.queue({"containerVersion": {"containerVersionId": "15", "name": "v15"}})
    result = await call("gtm_publish_version", version_path="accounts/1/containers/2/versions/15")
    assert http.requests[0]["uri"].split("?")[0].endswith("/versions/15:publish")
    assert result == {"compiler_error": False, "published_version_id": "15", "name": "v15"}


async def test_create_version_reports_new_workspace(http, monkeypatch):
    monkeypatch.setenv("GOOHLE_MCP_MODE", "write")
    http.queue(
        {
            "containerVersion": {"path": "accounts/1/containers/2/versions/16", "containerVersionId": "16", "name": "Add lead tag"},
            "newWorkspacePath": "accounts/1/containers/2/workspaces/4",
        }
    )
    result = await call("gtm_create_version", workspace_path=WS, name="Add lead tag", notes="form_submit -> generate_lead")
    assert http.requests[0]["body"] == {"name": "Add lead tag", "notes": "form_submit -> generate_lead"}
    assert result["version_id"] == "16"
    assert result["new_workspace_path"] == "accounts/1/containers/2/workspaces/4"


@pytest.mark.parametrize("bad", ["accounts/1/containers/2/tags/7", f"{WS}/cookies/1", "GTM-ABCD"])
async def test_bad_entity_paths(http, bad):
    with pytest.raises(ToolError, match="not a GTM entity path"):
        await call("gtm_get_entity", path=bad)


async def test_built_in_variables_are_sent_as_repeated_type(http):
    result = await call(
        "gtm_set_built_in_variables", workspace_path=WS, types=["clickText", "clickUrl"], dry_run=True
    )
    uri = result["would_send"]["uri"]
    assert "type=clickText" in uri and "type=clickUrl" in uri
