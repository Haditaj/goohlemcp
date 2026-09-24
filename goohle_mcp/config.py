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
