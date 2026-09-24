"""Small helpers shared by the tool modules."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Annotated, Any

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

DryRun = Annotated[
    bool,
    Field(
        description=(
            "If true, nothing is changed: the exact API request is returned for review. "
            "Works in every mode."
        )
    ),
]

_RELATIVE_DATE = re.compile(r"^(\d+)daysAgo$")


def resolve_date(value: str, *, today: date | None = None) -> str:
    """Accepts YYYY-MM-DD, 'today', 'yesterday' or 'NdaysAgo'; returns YYYY-MM-DD."""
    today = today or date.today()
    text = value.strip()
    if text == "today":
        return today.isoformat()
    if text == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    match = _RELATIVE_DATE.match(text)
    if match:
        return (today - timedelta(days=int(match.group(1)))).isoformat()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise ToolError(
            f"Invalid date '{value}'. Use YYYY-MM-DD, 'today', 'yesterday' or 'NdaysAgo'."
        ) from None


def changed_fields(**fields: Any) -> tuple[dict[str, Any], str]:
    """Builds a PATCH body and update mask from the arguments that were given."""
    body = {key: value for key, value in fields.items() if value is not None}
    if not body:
        raise ToolError("Nothing to update: pass at least one field to change.")
    return body, ",".join(body)


def drop_empty(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value not in (None, [], {}, "")}
