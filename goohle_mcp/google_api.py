"""Shared plumbing for calling Google APIs from tools.

Every tool goes through `execute` (reads) or `mutate` (writes), so error
translation, the write/publish permission gate, dry runs and the audit log
live in one place.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import anyio
import google_auth_httplib2
import httplib2
from google.auth.exceptions import RefreshError
from googleapiclient import discovery
from googleapiclient.errors import HttpError
from googleapiclient.http import HttpRequest, build_http
from mcp.server.mcpserver.exceptions import ToolError

from goohle_mcp import auth, config

_services: dict[tuple[str, str], Any] = {}
_services_lock = threading.Lock()

# Human-readable API names, used in "enable this API" hints.
_API_NAMES = {
    "analyticsadmin": "Google Analytics Admin API",
    "analyticsdata": "Google Analytics Data API",
    "searchconsole": "Google Search Console API",
    "tagmanager": "Tag Manager API",
    "sheets": "Google Sheets API",
}


def service(api: str, version: str) -> Any:
    """Returns a cached discovery client for `api`/`version`."""
    key = (api, version)
    with _services_lock:
        if key not in _services:
            try:
                creds = auth.get_credentials()
            except auth.AuthError as exc:
                raise ToolError(str(exc)) from exc
            _services[key] = discovery.build(
                api, version, credentials=creds, cache_discovery=False, static_discovery=True
            )
        return _services[key]


def reset_services() -> None:
    with _services_lock:
        _services.clear()


_HTTP_TIMEOUT = 120  # seconds; VPN links can be slow.
_MAX_PARALLEL = 4
_refresh_lock = threading.Lock()
_limiter: anyio.CapacityLimiter | None = None


def _new_http() -> Any:
    # httplib2 connections are not thread-safe, so every request gets its own.
    creds = auth.get_credentials()
    # Refresh once under a lock so parallel calls don't race on the same token.
    with _refresh_lock:
        if not creds.valid:
            creds.refresh(google_auth_httplib2.Request(build_http()))
    return google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=_HTTP_TIMEOUT))


def _run(request: HttpRequest, retries: int) -> Any:
    return request.execute(http=_new_http(), num_retries=retries)


async def execute(request: HttpRequest, *, retries: int = 2) -> Any:
    """Executes a request off the event loop, translating every failure into a ToolError."""
    global _limiter
    if _limiter is None:
        _limiter = anyio.CapacityLimiter(_MAX_PARALLEL)
    try:
        return await anyio.to_thread.run_sync(_run, request, retries, limiter=_limiter)
    except HttpError as exc:
        raise ToolError(describe_http_error(exc)) from exc
    except auth.AuthError as exc:
        raise ToolError(str(exc)) from exc
    except RefreshError as exc:
        raise ToolError(
            f"Google sign-in could not be refreshed ({exc}). If it says invalid_grant, the "
            "token expired (OAuth app in Testing mode): run `goohle-mcp auth --client-secrets ...` "
            "again and restart Claude."
        ) from exc
    except Exception as exc:  # Network-level failures (timeouts, resets, DNS, TLS).
        raise ToolError(
            f"Connection to Google failed: {type(exc).__name__}: {exc}. This is usually a "
            "network or VPN hiccup: retry this call once on its own; if it keeps failing, "
            "check the internet/VPN connection."
        ) from exc


async def collect(
    make_request: Callable[[str | None], HttpRequest],
    items_key: str,
    *,
    max_pages: int = 20,
) -> list[dict[str, Any]]:
    """Follows `nextPageToken` pagination and returns all items."""
    items: list[dict[str, Any]] = []
    token: str | None = None
    for _ in range(max_pages):
        response = await execute(make_request(token)) or {}
        items.extend(response.get(items_key, []))
        token = response.get("nextPageToken")
        if not token:
            break
    return items


def describe_request(request: HttpRequest) -> dict[str, Any]:
    body = json.loads(request.body) if request.body else None
    parts = urlsplit(request.uri)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k != "alt"])
    uri = urlunsplit(parts._replace(query=query))
    return {"method": request.method, "uri": uri, "body": body}


async def mutate(
    tool: str,
    request: HttpRequest,
    *,
    dry_run: bool,
    level: str = "write",
    summary: dict[str, Any] | None = None,
) -> Any:
    """Executes a change after checking the permission mode.

    With `dry_run` the request is returned instead of sent, in any mode, so the
    exact change can be reviewed before enabling writes. `summary` replaces the
    full request in the dry-run result and audit log (for very large bodies).
    """
    summary = summary or describe_request(request)
    if dry_run:
        _audit(tool, summary, "dry_run")
        return {"dry_run": True, "would_send": summary}
    if not config.mode_allows(level):
        raise ToolError(
            f"'{tool}' changes live {level}-level settings, but this server runs in "
            f"'{config.mode()}' mode. Call it again with dry_run=true to preview the "
            f"change, or ask the user to set GOOHLE_MCP_MODE={level} in the MCP server "
            "config and restart Claude."
        )
    try:
        # No automatic retries: a retried create after a timeout could duplicate it.
        result = await execute(request, retries=0)
    except ToolError as exc:
        _audit(tool, summary, "error", str(exc))
        raise
    _audit(tool, summary, "ok")
    # Deletes and sitemap submits answer with an empty (or non-JSON) body.
    return result if isinstance(result, dict) and result else {"ok": True}


def _audit(tool: str, summary: dict[str, Any], status: str, error: str | None = None) -> None:
    entry = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": tool,
        "status": status,
        "mode": config.mode(),
        **summary,
    }
    if error:
        entry["error"] = error
    path = config.audit_log_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # Auditing must never block the change itself.


def describe_http_error(exc: HttpError) -> str:
    """Turns a Google API error into a message that says what to do next."""
    status = exc.resp.status if exc.resp is not None else 0
    message, reason = _error_parts(exc)
    api = _api_from_uri(exc.uri or "")
    api_name = _API_NAMES.get(api, "the Google API")

    if status == 401:
        hint = f"The Google sign-in is missing or expired. {auth.SETUP_HINT}"
    elif status == 403 and reason in ("SERVICE_DISABLED", "accessNotConfigured"):
        hint = (
            f"{api_name} is not enabled in the Google Cloud project behind your OAuth "
            "client. Enable it in Google Cloud Console > APIs & Services > Library, "
            "wait a minute, then retry."
        )
    elif status == 403 and (
        reason == "ACCESS_TOKEN_SCOPE_INSUFFICIENT" or "insufficient" in message.lower()
    ):
        hint = (
            "The stored sign-in does not include the permission this call needs. Re-run "
            "`goohle-mcp auth --client-secrets ...` without --read-only, then restart Claude."
        )
    elif status == 403:
        hint = (
            "The signed-in Google account has no access (or too little access) to this "
            "resource. Check the ID with the matching list tool, or grant the account "
            "Editor/Publish rights in the product's admin settings."
        )
    elif status == 404:
        hint = "Not found. Check the ID or path with the matching list tool."
    elif status == 429:
        hint = "Quota exceeded. Wait a bit, narrow the request (fewer rows or a shorter date range), then retry."
    elif status == 400:
        hint = (
            "The request was rejected as invalid. For GA4 reports, check names with "
            "ga4_get_metadata; for GTM, compare with an existing entity from gtm_get_entity."
        )
    elif status == 409:
        hint = (
            "Conflict: the resource changed since it was read (fingerprint mismatch) or "
            "already exists. Re-read it and retry."
        )
    else:
        hint = "Unexpected Google API error."
    return f"Google API error {status}: {message}\nHint: {hint}"


def _error_parts(exc: HttpError) -> tuple[str, str]:
    message = exc._get_reason() or ""
    reason = ""
    try:
        payload = json.loads(exc.content.decode("utf-8"))
        err = payload.get("error", {})
        message = err.get("message", message)
        for detail in err.get("details", []) or []:
            if isinstance(detail, dict) and detail.get("reason"):
                reason = detail["reason"]
                break
        if not reason:
            for item in err.get("errors", []) or []:
                if item.get("reason"):
                    reason = item["reason"]
                    break
    except (ValueError, AttributeError):
        pass
    return message.strip(), reason


def _api_from_uri(uri: str) -> str:
    host = uri.split("//", 1)[-1].split("/", 1)[0]
    if host.startswith("analyticsadmin"):
        return "analyticsadmin"
    if host.startswith("analyticsdata"):
        return "analyticsdata"
    if host.startswith("searchconsole") or "/webmasters/" in uri:
        return "searchconsole"
    if host.startswith("tagmanager"):
        return "tagmanager"
    if host.startswith("sheets"):
        return "sheets"
    return ""
