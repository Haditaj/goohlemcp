import pytest
from mcp.server.mcpserver.exceptions import ToolError

from conftest import call


@pytest.fixture
def only_moa(monkeypatch):
    monkeypatch.setenv("GOOHLE_MCP_GA4_PROPERTIES", "489808888")
    monkeypatch.setenv("GOOHLE_MCP_GSC_SITES", "sc-domain:moa.coffee")
    monkeypatch.setenv("GOOHLE_MCP_GTM_CONTAINERS", "260880634")


async def test_other_resources_are_refused(http, only_moa):
    with pytest.raises(ToolError, match="outside the resources"):
        await call("ga4_run_report", property_id="111", metrics=["sessions"])
    with pytest.raises(ToolError, match="outside the resources"):
        await call("ga4_archive_custom_dimension", name="properties/111/customDimensions/2", dry_run=True)
    with pytest.raises(ToolError, match="outside the resources"):
        await call("gsc_list_sitemaps", site_url="sc-domain:boolooz.com")
    with pytest.raises(ToolError, match="outside the resources"):
        await call("gtm_get_entity", path="accounts/1/containers/999/workspaces/3/tags/4")
    with pytest.raises(ToolError, match="outside the resources"):
        await call("gtm_publish_version", version_path="accounts/1/containers/999/versions/5", dry_run=True)
    with pytest.raises(ToolError, match="disabled"):
        await call("ga4_create_property", account_id="1", display_name="x", time_zone="UTC", dry_run=True)
    with pytest.raises(ToolError, match="disabled"):
        await call("gtm_create_container", account_id="1", name="x", dry_run=True)
    assert http.requests == []


async def test_allowed_resources_work_and_lists_are_filtered(http, only_moa):
    http.queue({"siteEntry": [{"siteUrl": "sc-domain:boolooz.com"}, {"siteUrl": "sc-domain:moa.coffee"}]})
    assert (await call("gsc_list_sites"))["sites"] == [{"siteUrl": "sc-domain:moa.coffee"}]

    http.queue({"accountSummaries": [
        {"account": "accounts/1", "propertySummaries": [{"property": "properties/489808888"}, {"property": "properties/111"}]},
        {"account": "accounts/2", "propertySummaries": [{"property": "properties/222"}]},
    ]})
    accounts = (await call("ga4_list_accounts"))["accounts"]
    assert [a["account"] for a in accounts] == ["accounts/1"]
    assert [p["property"] for p in accounts[0]["properties"]] == ["properties/489808888"]

    http.queue({"container": [{"path": "accounts/6/containers/260880634", "containerId": "260880634"},
                              {"path": "accounts/6/containers/999", "containerId": "999"}]})
    containers = (await call("gtm_list_containers", account_id="6"))["containers"]
    assert [c["path"] for c in containers] == ["accounts/6/containers/260880634"]

    http.queue({"rows": []})
    await call("ga4_run_report", property_id="489808888", metrics=["sessions"])
