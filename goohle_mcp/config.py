"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

# Permission levels, from least to most powerful.
MODES = ("read", "write", "publish")


def mode() -> str:
    """Current permission level (GOOHLE_MCP_MODE). Defaults to read-only."""
    value = os.environ.get("GOOHLE_MCP_MODE", "read").strip().lower()
    return value if value in MODES else "read"


def mode_allows(level: str) -> bool:
    return MODES.index(mode()) >= MODES.index(level)


def config_dir() -> Path:
    override = os.environ.get("GOOHLE_MCP_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "goohle-mcp"


def token_file() -> Path:
    override = os.environ.get("GOOHLE_MCP_TOKEN_FILE")
    return Path(override).expanduser() if override else config_dir() / "token.json"


def service_account_file() -> Path | None:
    value = os.environ.get("GOOHLE_MCP_SERVICE_ACCOUNT_FILE")
    return Path(value).expanduser() if value else None


def audit_log_file() -> Path:
    override = os.environ.get("GOOHLE_MCP_AUDIT_LOG")
    return Path(override).expanduser() if override else config_dir() / "audit.jsonl"


# Optional allowlists (comma-separated). When set, tools refuse anything else.
_ALLOWLIST_VARS = {
    "ga4": "GOOHLE_MCP_GA4_PROPERTIES",  # e.g. 489808888
    "gsc": "GOOHLE_MCP_GSC_SITES",  # e.g. sc-domain:moa.coffee
    "gtm": "GOOHLE_MCP_GTM_CONTAINERS",  # container IDs, e.g. 260880634
}


def allowlist(kind: str) -> set[str] | None:
    raw = os.environ.get(_ALLOWLIST_VARS[kind], "").strip()
    if not raw:
        return None
    values = {v.strip() for v in raw.split(",") if v.strip()}
    if kind == "ga4":
        values = {v.removeprefix("properties/") for v in values}
    return values


def require_allowed(kind: str, value: str) -> None:
    allowed = allowlist(kind)
    if allowed is not None and value not in allowed:
        from mcp.server.mcpserver.exceptions import ToolError

        raise ToolError(
            f"'{value}' is outside the resources this server may use "
            f"({_ALLOWLIST_VARS[kind]}={','.join(sorted(allowed))}). Do not retry with it."
        )
