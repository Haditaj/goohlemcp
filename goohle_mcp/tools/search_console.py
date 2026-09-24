"""Google Search Console: search performance, URL inspection and sitemaps."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from goohle_mcp import config
from goohle_mcp.app import CHANGE, CREATE, READ, mcp
from goohle_mcp.google_api import execute, mutate, service
from goohle_mcp.tools.common import DryRun, resolve_date

SiteUrl = Annotated[
    str,
    Field(
        description=(
            "Search Console property exactly as listed by gsc_list_sites: "
            "'https://example.com/' (URL-prefix) or 'sc-domain:example.com' (domain property)."
        )
    ),
]

Dimension = Literal["query", "page", "country", "device", "date", "searchAppearance", "hour"]


class SearchFilter(BaseModel):
    dimension: Literal["query", "page", "country", "device", "searchAppearance"]
    operator: Literal["equals", "notEquals", "contains", "notContains", "includingRegex", "excludingRegex"] = "contains"
    expression: str = Field(description="Value to match. Countries are ISO 3166-1 alpha-3 (e.g. 'irn'); devices are DESKTOP/MOBILE/TABLET.")


def _site(site_url: str) -> str:
    config.require_allowed("gsc", site_url)
    return site_url


def _gsc() -> Any:
    return service("searchconsole", "v1")


@mcp.tool(name="gsc_list_sites", title="List Search Console sites", annotations=READ)
async def gsc_list_sites() -> dict[str, Any]:
    """Lists Search Console properties the signed-in user can access, with permission level."""
    response = await execute(_gsc().sites().list())
    allowed = config.allowlist("gsc")
    sites = response.get("siteEntry", [])
    return {"sites": [x for x in sites if allowed is None or x.get("siteUrl") in allowed]}


@mcp.tool(name="gsc_search_analytics", title="Query Search Console performance", annotations=READ)
async def gsc_search_analytics(
    site_url: SiteUrl,
    dimensions: Annotated[
        list[Dimension] | None,
        Field(description="Group by these, e.g. ['query'], ['page'], ['date'], ['query', 'page']. Empty = site totals."),
    ] = None,
    start_date: Annotated[str, Field(description="YYYY-MM-DD, 'today', 'yesterday' or 'NdaysAgo'.")] = "30daysAgo",
    end_date: Annotated[str, Field(description="Data usually lags 2-3 days.")] = "3daysAgo",
    filters: Annotated[
        list[SearchFilter] | None,
        Field(description="All filters must match, e.g. [{'dimension': 'page', 'operator': 'contains', 'expression': '/blog/'}]."),
    ] = None,
    search_type: Literal["web", "image", "video", "news", "discover", "googleNews"] = "web",
    row_limit: Annotated[int, Field(ge=1, le=25000)] = 100,
    start_row: Annotated[int, Field(ge=0)] = 0,
    aggregation_type: Literal["auto", "byPage", "byProperty"] = "auto",
    data_state: Annotated[
        Literal["final", "all"], Field(description="'all' includes fresh, not-yet-final data.")
    ] = "final",
) -> dict[str, Any]:
    """Returns clicks, impressions, CTR and average position from Google Search.

    Rows are sorted by clicks. Examples: top queries (dimensions ['query']); pages losing
    traffic (run two date ranges with ['page'] and compare); queries for one page
    (['query'] with a page filter). Page with `start_row` / `next_start_row`.
    """
    dims = list(dimensions or [])
    body: dict[str, Any] = {
        "startDate": resolve_date(start_date),
        "endDate": resolve_date(end_date),
        "dimensions": dims,
        "type": search_type,
        "rowLimit": row_limit,
        "startRow": start_row,
        "aggregationType": aggregation_type,
        "dataState": data_state,
    }
    if filters:
        body["dimensionFilterGroups"] = [
            {"groupType": "and", "filters": [f.model_dump() for f in filters]}
        ]
    response = await execute(_gsc().searchanalytics().query(siteUrl=_site(site_url), body=body))
    rows = []
    for row in response.get("rows", []):
        item: dict[str, Any] = dict(zip(dims, row.get("keys", [])))
        item.update(
            clicks=row.get("clicks", 0),
            impressions=row.get("impressions", 0),
            ctr=round(row.get("ctr", 0.0), 4),
            position=round(row.get("position", 0.0), 1),
        )
        rows.append(item)
    result: dict[str, Any] = {
        "date_range": [body["startDate"], body["endDate"]],
        "rows": rows,
        "aggregation": response.get("responseAggregationType"),
    }
    if len(rows) == row_limit:
        result["next_start_row"] = start_row + row_limit
    return result


@mcp.tool(name="gsc_inspect_url", title="Inspect URL in Google index", annotations=READ)
async def gsc_inspect_url(
    site_url: SiteUrl,
    url: Annotated[str, Field(description="Full page URL inside the property, e.g. 'https://example.com/blog/post'.")],
    language_code: str = "en-US",
) -> dict[str, Any]:
    """Shows Google's index status for a page: indexed or not and why, canonical,
    last crawl, robots/noindex, mobile usability and rich results.

    Note: the API cannot request indexing; that stays a manual step in Search Console.
    """
    body = {"inspectionUrl": url, "siteUrl": _site(site_url), "languageCode": language_code}
    response = await execute(_gsc().urlInspection().index().inspect(body=body))
    return response.get("inspectionResult", response)


@mcp.tool(name="gsc_list_sitemaps", title="List sitemaps", annotations=READ)
async def gsc_list_sitemaps(site_url: SiteUrl) -> dict[str, Any]:
    """Lists submitted sitemaps with last download time, warnings, errors and URL counts."""
    response = await execute(_gsc().sitemaps().list(siteUrl=_site(site_url)))
    return {"sitemaps": response.get("sitemap", [])}


@mcp.tool(name="gsc_submit_sitemap", title="Submit sitemap", annotations=CREATE)
async def gsc_submit_sitemap(
    site_url: SiteUrl,
    sitemap_url: Annotated[str, Field(description="e.g. 'https://example.com/sitemap.xml'.")],
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Submits (or resubmits) a sitemap so Google fetches it again."""
    request = _gsc().sitemaps().submit(siteUrl=_site(site_url), feedpath=sitemap_url)
    return await mutate("gsc_submit_sitemap", request, dry_run=dry_run)


@mcp.tool(name="gsc_delete_sitemap", title="Remove sitemap", annotations=CHANGE)
async def gsc_delete_sitemap(
    site_url: SiteUrl,
    sitemap_url: str,
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Removes a sitemap from Search Console (the file on the site is untouched)."""
    request = _gsc().sitemaps().delete(siteUrl=_site(site_url), feedpath=sitemap_url)
    return await mutate("gsc_delete_sitemap", request, dry_run=dry_run)
