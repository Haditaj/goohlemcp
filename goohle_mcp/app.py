"""The MCP server instance that every tool module registers with."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

INSTRUCTIONS = """\
Tools for one person's Google marketing stack: Google Analytics 4 (ga4_*),
Search Console (gsc_*), Google Tag Manager (gtm_*) and Google Sheets (sheets_*).

How to work:
- Start with a list tool (ga4_list_accounts, gsc_list_sites, gtm_list_accounts) to find IDs.
- GA4 property IDs are numbers (123456789), not measurement IDs (G-XXXX).
- Before building a GA4 report with unfamiliar fields, use ga4_get_metadata.
- Tools that change something accept dry_run. Before any change, show the user what
  will change (a dry_run result is ideal) and get a clear yes.
- GTM edits happen in a workspace and are not live until a version is created
  (gtm_create_version) and published (gtm_publish_version). Run gtm_quick_preview
  to catch compiler errors first. Never publish without explicit user approval.
- For exports into a sheet: run the report with save_csv, shape the CSV to match the
  tab's header (sheets_get_info), then sheets_append_csv. Never paste large data by hand.
- After a meaningful GA4 or GTM change, offer to add a GA4 annotation
  (ga4_create_annotation) so the change is visible in reports later.
"""

mcp = MCPServer(name="goohle_mcp", instructions=INSTRUCTIONS)

READ = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)
# Adds something new; existing configuration is untouched.
CREATE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
)
# Overwrites, archives, deletes or publishes existing configuration.
CHANGE = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=True
)
