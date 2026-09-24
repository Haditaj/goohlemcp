"""Test fixtures: real discovery clients, fake HTTP, no Google account needed."""

from __future__ import annotations

import json
from typing import Any

import httplib2
import pytest
from google.auth.credentials import AnonymousCredentials

from goohle_mcp import auth, google_api
from goohle_mcp import prompts  # noqa: F401  (registers prompts)
from goohle_mcp.app import mcp
from goohle_mcp.tools import ga4, search_console, tag_manager  # noqa: F401  (registers tools)


class FakeHttp:
    """Records requests and replays queued (status, body) responses."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.responses: list[tuple[int, Any]] = []

    def queue(self, body: Any = None, status: int = 200) -> None:
        self.responses.append((status, body))

    def request(self, uri, method="GET", body=None, headers=None, **_: Any):
        self.requests.append(
            {"uri": uri, "method": method, "body": json.loads(body) if body else None}
        )
        status, payload = self.responses.pop(0) if self.responses else (200, {})
        content = json.dumps(payload if payload is not None else {}).encode()
        return httplib2.Response({"status": status, "content-type": "application/json"}), content


@pytest.fixture
def http(monkeypatch, tmp_path) -> FakeHttp:
    fake = FakeHttp()
    monkeypatch.setenv("GOOHLE_MCP_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("GOOHLE_MCP_MODE", raising=False)
    monkeypatch.setattr(auth, "get_credentials", lambda: AnonymousCredentials())
    monkeypatch.setattr(google_api, "_new_http", lambda: fake)
    google_api.reset_services()
    yield fake
    google_api.reset_services()


async def call(tool: str, /, **arguments: Any) -> Any:
    result = await mcp.call_tool(tool, arguments)
    return result.structured_content
