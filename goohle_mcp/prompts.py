"""Ready-made workflows, exposed as MCP prompts (slash commands in Claude Code)."""

from __future__ import annotations

from goohle_mcp.app import mcp


@mcp.prompt(name="tracking_audit", title="Audit GA4 + GTM tracking")
def tracking_audit(ga4_property_id: str, gtm_container_path: str) -> str:
    return f"""Audit the tracking setup of GA4 property {ga4_property_id} and GTM container {gtm_container_path}.

1. ga4_list_data_streams: note each web stream's measurement ID.
2. gtm_get_version (live): check that a Google tag (googtag) uses that measurement ID, fires on
   All Pages, and that no GA4 tag points at a different or unknown ID.
3. List GA4 event tags (type gaawe) and their triggers; flag paused tags, tags without triggers,
   duplicate events and inconsistent event/parameter naming (GA4 recommends snake_case).
4. ga4_run_report for eventName x eventCount (last 28 days) and ga4_list_key_events: flag key
   events that received no data, and frequent events that look like conversions but are not key events.
5. ga4_list_custom_definitions: flag event parameters sent by GTM tags that are not registered as
   custom dimensions, and custom dimensions with no data.
6. ga4_get_data_retention: flag retention of two months.

Report findings ordered by impact with a concrete fix for each. Do not change anything; offer
fixes afterwards and show dry_run output before any change."""


@mcp.prompt(name="seo_review", title="Search Console performance review")
def seo_review(site_url: str, days: str = "28") -> str:
    return f"""Review Google Search performance for {site_url}.

1. gsc_search_analytics with dimensions ['date'] for the last {days} days and the {days} days
   before that; summarise the change in clicks, impressions, CTR and position.
2. Top queries and top pages for both periods; list the biggest winners and losers.
3. Quick wins: queries with average position 5-15 and high impressions, and pages with high
   impressions but CTR clearly below similar pages (title/meta description candidates).
4. gsc_list_sitemaps: flag errors, warnings or stale downloads.
5. gsc_inspect_url for the 3 biggest losing pages: report index status and canonical issues.
6. If a GA4 property exists for the site, compare organic landing pages (ga4_run_report with
   sessionDefaultChannelGroup = 'Organic Search') with Search Console clicks.

Finish with a prioritised action list."""


@mcp.prompt(name="weekly_report", title="Weekly marketing report")
def weekly_report(ga4_property_id: str, site_url: str = "") -> str:
    gsc_step = (
        f"\n3. Search Console for {site_url}: clicks, impressions, top 10 queries and pages vs last week."
        if site_url
        else ""
    )
    return f"""Write a weekly report for GA4 property {ga4_property_id}: last 7 complete days vs the 7 days before.

1. Sessions, users, key events and revenue (if any) by sessionDefaultChannelGroup.
2. Top 10 landing pages by sessions with key-event rate.{gsc_step}

Keep it short: headline numbers, what changed and the likely reasons, and 3 recommended actions."""
