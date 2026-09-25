"""Google credentials: a cached OAuth user token, a service account, or ADC."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import google.auth
from google.auth.credentials import Credentials
from google.auth.exceptions import DefaultCredentialsError
from google.oauth2 import credentials as user_credentials
from google.oauth2 import service_account

from goohle_mcp import config

READ_SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/tagmanager.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

WRITE_SCOPES = READ_SCOPES + [
    "https://www.googleapis.com/auth/analytics.edit",
    "https://www.googleapis.com/auth/webmasters",
    "https://www.googleapis.com/auth/tagmanager.edit.containers",
    "https://www.googleapis.com/auth/tagmanager.edit.containerversions",
    "https://www.googleapis.com/auth/tagmanager.publish",
    "https://www.googleapis.com/auth/spreadsheets",
]

SETUP_HINT = (
    "Run `goohle-mcp auth --client-secrets /path/to/client_secret.json` once to sign in "
    "with the Google account that has access to your GA4 / Search Console / GTM, "
    "or set GOOHLE_MCP_SERVICE_ACCOUNT_FILE to a service-account key that was added "
    "as a user in those products."
)


class AuthError(Exception):
    """No usable Google credentials were found."""


_lock = threading.Lock()
_credentials: Credentials | None = None


def scopes_for_mode() -> list[str]:
    return READ_SCOPES if config.mode() == "read" else WRITE_SCOPES


def _load() -> Credentials:
    token = config.token_file()
    if token.exists():
        # Access tokens are refreshed on demand by the HTTP transport.
        return user_credentials.Credentials.from_authorized_user_file(str(token))

    sa_file = config.service_account_file()
    if sa_file:
        return service_account.Credentials.from_service_account_file(
            str(sa_file), scopes=scopes_for_mode()
        )

    try:
        creds, _ = google.auth.default(scopes=scopes_for_mode())
        return creds
    except DefaultCredentialsError as exc:
        raise AuthError(f"No Google credentials found. {SETUP_HINT}") from exc


def get_credentials() -> Credentials:
    """Returns process-wide credentials, loading them on first use."""
    global _credentials
    with _lock:
        if _credentials is None:
            _credentials = _load()
        return _credentials


def reset_credentials() -> None:
    global _credentials
    with _lock:
        _credentials = None


def _write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(content)


def login(
    client_secrets: Path,
    *,
    read_only: bool = False,
    port: int = 0,
    open_browser: bool = True,
) -> Path:
    """Runs the browser OAuth flow and stores the resulting token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    scopes = READ_SCOPES if read_only else WRITE_SCOPES
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), scopes=scopes)
    creds = flow.run_local_server(
        port=port,
        open_browser=open_browser,
        access_type="offline",
        prompt="consent",
    )
    path = config.token_file()
    _write_private(path, creds.to_json())
    reset_credentials()
    return path
