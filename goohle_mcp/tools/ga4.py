"""Google Analytics 4: reports (Data API) and property configuration (Admin API)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from goohle_mcp.app import CHANGE, CREATE, READ, mcp
from goohle_mcp.google_api import collect, execute, mutate, service
from goohle_mcp.tools.common import DryRun, changed_fields, drop_empty, resolve_date

PropertyId = Annotated[
    str,
    Field(
        description=(
            "GA4 property ID, e.g. '123456789' or 'properties/123456789'. "
            "Not the G-XXXX measurement ID. Find it with ga4_list_accounts."
        )
    ),
]
Metrics = Annotated[
    list[str],
    Field(
        min_length=1,
        max_length=10,
        description="Metric API names, e.g. ['sessions', 'totalUsers', 'keyEvents', 'purchaseRevenue'].",
    ),
]
Dimensions = Annotated[
    list[str] | None,
    Field(
        max_length=9,
        description="Dimension API names, e.g. ['date', 'sessionDefaultChannelGroup', 'pagePath', 'country'].",
    ),
]
FilterExpression = Annotated[
    dict[str, Any] | None,
    Field(
        description=(
            "GA4 Data API FilterExpression, e.g. "
            '{"filter": {"fieldName": "country", "stringFilter": {"value": "Iran"}}} or '
            '{"andGroup": {"expressions": [...]}}; metric filters use numericFilter.'
        )
    ),
]


def _admin() -> Any:
    return service("analyticsadmin", "v1beta")


def _admin_alpha() -> Any:
    return service("analyticsadmin", "v1alpha")


def _data() -> Any:
    return service("analyticsdata", "v1beta")


def property_name(property_id: str) -> str:
    value = str(property_id).strip().removeprefix("properties/")
    if not value.isdigit():
        raise ToolError(
            f"'{property_id}' is not a GA4 property ID. Use the numeric ID "
            "(e.g. 123456789) from ga4_list_accounts, not a G-XXXX measurement ID."
        )
    return f"properties/{value}"


def _child_name(name: str, collection: str) -> str:
    value = name.strip()
    if not re.fullmatch(rf"properties/\d+/{collection}/[^/]+", value):
        raise ToolError(
            f"'{name}' is not a {collection} resource name; expected "
            f"'properties/<id>/{collection}/<id>' as returned by the list tools."
        )
    return value


def _order_bys(order_by: list[str], metrics: list[str], dimensions: list[str]) -> list[dict]:
    result = []
    for spec in order_by:
        desc = spec.startswith("-")
        field = spec.lstrip("-+")
        if field in metrics:
            result.append({"metric": {"metricName": field}, "desc": desc})
        elif field in dimensions:
            result.append({"dimension": {"dimensionName": field}, "desc": desc})
        else:
            raise ToolError(f"order_by '{spec}' must name one of the requested metrics or dimensions.")
    return result


def _metric_value(raw: str, metric_type: str) -> int | float | str:
    try:
        return int(raw) if metric_type == "TYPE_INTEGER" else float(raw)
    except (TypeError, ValueError):
        return raw


def format_report(response: dict[str, Any], offset: int = 0) -> dict[str, Any]:
    """Flattens a Data API report into a list of {field: value} rows."""
    dim_names = [h["name"] for h in response.get("dimensionHeaders", [])]
    metric_headers = response.get("metricHeaders", [])
    rows = []
    for row in response.get("rows", []):
        item: dict[str, Any] = {}
        for name, value in zip(dim_names, row.get("dimensionValues", [])):
            item[name] = value.get("value")
        for header, value in zip(metric_headers, row.get("metricValues", [])):
            item[header["name"]] = _metric_value(value.get("value"), header.get("type", ""))
        rows.append(item)
    row_count = response.get("rowCount", len(rows))
    result: dict[str, Any] = {"row_count": row_count, "rows": rows}
    if offset + len(rows) < row_count:
        result["next_offset"] = offset + len(rows)
    meta = response.get("metadata", {})
    notes = drop_empty(
        {
            "currency_code": meta.get("currencyCode"),
            "time_zone": meta.get("timeZone"),
            "subject_to_thresholding": meta.get("subjectToThresholding"),
            "sampling": meta.get("samplingMetadatas"),
            "data_loss_from_other_row": meta.get("dataLossFromOtherRow"),
        }
    )
    if notes:
        result["metadata"] = notes
    return result


# --- Read tools ---------------------------------------------------------------


@mcp.tool(name="ga4_list_accounts", title="List GA4 accounts and properties", annotations=READ)
async def ga4_list_accounts() -> dict[str, Any]:
    """Lists every GA4 account and property the signed-in user can access, with their IDs."""
    summaries = await collect(
        lambda token: _admin().accountSummaries().list(pageSize=200, pageToken=token),
        "accountSummaries",
    )
    return {
        "accounts": [
            {
                "account": s.get("account"),
                "display_name": s.get("displayName"),
                "properties": [
                    {
                        "property": p.get("property"),
                        "display_name": p.get("displayName"),
                        "property_type": p.get("propertyType"),
                    }
                    for p in s.get("propertySummaries", [])
                ],
            }
            for s in summaries
        ]
    }


@mcp.tool(name="ga4_get_property", title="Get GA4 property settings", annotations=READ)
async def ga4_get_property(property_id: PropertyId) -> dict[str, Any]:
    """Returns a property's settings: name, time zone, currency, industry, service level."""
    return await execute(_admin().properties().get(name=property_name(property_id)))


@mcp.tool(name="ga4_list_data_streams", title="List GA4 data streams", annotations=READ)
async def ga4_list_data_streams(property_id: PropertyId) -> dict[str, Any]:
    """Lists web/app data streams, including each web stream's G-XXXX measurement ID and URL.

    Use the measurement ID to check that GTM's Google tag points at the right property.
    """
    streams = await collect(
        lambda token: _admin()
        .properties()
        .dataStreams()
        .list(parent=property_name(property_id), pageSize=200, pageToken=token),
        "dataStreams",
    )
    return {
        "data_streams": [
            drop_empty(
                {
                    "name": s.get("name"),
                    "type": s.get("type"),
                    "display_name": s.get("displayName"),
                    "measurement_id": s.get("webStreamData", {}).get("measurementId"),
                    "default_uri": s.get("webStreamData", {}).get("defaultUri"),
                    "android_package": s.get("androidAppStreamData", {}).get("packageName"),
                    "ios_bundle_id": s.get("iosAppStreamData", {}).get("bundleId"),
                }
            )
            for s in streams
        ]
    }


@mcp.tool(name="ga4_get_metadata", title="Find GA4 dimensions and metrics", annotations=READ)
async def ga4_get_metadata(
    property_id: PropertyId,
    search: Annotated[
        str | None,
        Field(description="Case-insensitive text to match in API name, UI name or category, e.g. 'revenue'."),
    ] = None,
    kind: Literal["dimensions", "metrics", "both"] = "both",
    custom_only: Annotated[bool, Field(description="Only custom dimensions/metrics.")] = False,
) -> dict[str, Any]:
    """Lists the dimension and metric API names usable in reports for this property.

    Includes the property's custom definitions (customEvent:..., customUser:...).
    Narrow the output with `search` - the full list has hundreds of entries.
    """
    meta = await execute(_data().properties().getMetadata(name=f"{property_name(property_id)}/metadata"))
    needle = (search or "").lower()

    def keep(item: dict[str, Any]) -> bool:
        if custom_only and not item.get("customDefinition"):
            return False
        if not needle:
            return True
        text = " ".join(str(item.get(k, "")) for k in ("apiName", "uiName", "category")).lower()
        return needle in text

    def compact(item: dict[str, Any]) -> dict[str, Any]:
        out = {"api_name": item.get("apiName"), "ui_name": item.get("uiName"), "category": item.get("category")}
        if item.get("type"):
            out["type"] = item["type"]
        if item.get("customDefinition"):
            out["custom"] = True
        if needle:
            out["description"] = item.get("description")
        return out

    result: dict[str, Any] = {}
    if kind in ("dimensions", "both"):
        result["dimensions"] = [compact(d) for d in meta.get("dimensions", []) if keep(d)]
    if kind in ("metrics", "both"):
        result["metrics"] = [compact(m) for m in meta.get("metrics", []) if keep(m)]
    return result


@mcp.tool(name="ga4_run_report", title="Run a GA4 report", annotations=READ)
async def ga4_run_report(
    property_id: PropertyId,
    metrics: Metrics,
    dimensions: Dimensions = None,
    start_date: Annotated[str, Field(description="YYYY-MM-DD, 'today', 'yesterday' or 'NdaysAgo'.")] = "28daysAgo",
    end_date: Annotated[str, Field(description="YYYY-MM-DD, 'today', 'yesterday' or 'NdaysAgo'.")] = "yesterday",
    compare_start_date: Annotated[
        str | None,
        Field(description="Optional second date range to compare against; rows then get a 'dateRange' column."),
    ] = None,
    compare_end_date: str | None = None,
    dimension_filter: FilterExpression = None,
    metric_filter: FilterExpression = None,
    order_by: Annotated[
        list[str] | None,
        Field(description="Fields to sort by; prefix '-' for descending, e.g. ['-sessions'] or ['date']."),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=10000)] = 100,
    offset: Annotated[int, Field(ge=0)] = 0,
    keep_empty_rows: bool = False,
) -> dict[str, Any]:
    """Runs a GA4 Data API report and returns flat rows of dimension and metric values.

    Examples: traffic by channel (dimensions ['sessionDefaultChannelGroup'], metrics
    ['sessions','keyEvents']); top landing pages (['landingPagePlusQueryString'],
    ['sessions'], order_by ['-sessions']); daily trend (['date'], order_by ['date']).
    Page through large results with `offset` / `next_offset`.
    """
    dimensions = dimensions or []
    date_ranges = [{"startDate": start_date, "endDate": end_date, "name": "current"}]
    if compare_start_date or compare_end_date:
        if not (compare_start_date and compare_end_date):
            raise ToolError("Pass both compare_start_date and compare_end_date.")
        date_ranges.append({"startDate": compare_start_date, "endDate": compare_end_date, "name": "previous"})
    body: dict[str, Any] = {
        "metrics": [{"name": m} for m in metrics],
        "dimensions": [{"name": d} for d in dimensions],
        "dateRanges": date_ranges,
        "limit": limit,
        "offset": offset,
        "keepEmptyRows": keep_empty_rows,
    }
    if dimension_filter:
        body["dimensionFilter"] = dimension_filter
    if metric_filter:
        body["metricFilter"] = metric_filter
    if order_by:
        body["orderBys"] = _order_bys(order_by, metrics, dimensions)
    response = await execute(_data().properties().runReport(property=property_name(property_id), body=body))
    return format_report(response, offset)


@mcp.tool(name="ga4_run_realtime_report", title="Run a GA4 realtime report", annotations=READ)
async def ga4_run_realtime_report(
    property_id: PropertyId,
    metrics: Annotated[
        list[str], Field(min_length=1, description="e.g. ['activeUsers', 'eventCount', 'keyEvents'].")
    ],
    dimensions: Annotated[
        list[str] | None, Field(description="e.g. ['unifiedScreenName', 'eventName', 'country', 'deviceCategory'].")
    ] = None,
    minutes_ago: Annotated[
        int, Field(ge=0, le=59, description="Look-back window in minutes (standard properties allow up to 29).")
    ] = 29,
    dimension_filter: FilterExpression = None,
    limit: Annotated[int, Field(ge=1, le=10000)] = 100,
) -> dict[str, Any]:
    """Shows what is happening on the site right now (last 30 minutes).

    Handy to verify a new GTM tag or event actually reaches GA4.
    """
    body: dict[str, Any] = {
        "metrics": [{"name": m} for m in metrics],
        "dimensions": [{"name": d} for d in dimensions or []],
        "minuteRanges": [{"startMinutesAgo": minutes_ago, "endMinutesAgo": 0}],
        "limit": limit,
    }
    if dimension_filter:
        body["dimensionFilter"] = dimension_filter
    response = await execute(
        _data().properties().runRealtimeReport(property=property_name(property_id), body=body)
    )
    return format_report(response)


@mcp.tool(name="ga4_list_custom_definitions", title="List GA4 custom dimensions and metrics", annotations=READ)
async def ga4_list_custom_definitions(property_id: PropertyId) -> dict[str, Any]:
    """Lists the property's custom dimensions and custom metrics (event parameter registrations)."""
    parent = property_name(property_id)
    dims = await collect(
        lambda token: _admin().properties().customDimensions().list(parent=parent, pageSize=200, pageToken=token),
        "customDimensions",
    )
    metrics = await collect(
        lambda token: _admin().properties().customMetrics().list(parent=parent, pageSize=200, pageToken=token),
        "customMetrics",
    )
    return {"custom_dimensions": dims, "custom_metrics": metrics}


@mcp.tool(name="ga4_list_key_events", title="List GA4 key events", annotations=READ)
async def ga4_list_key_events(property_id: PropertyId) -> dict[str, Any]:
    """Lists key events (formerly conversions) with their counting method."""
    events = await collect(
        lambda token: _admin()
        .properties()
        .keyEvents()
        .list(parent=property_name(property_id), pageSize=200, pageToken=token),
        "keyEvents",
    )
    return {"key_events": events}


@mcp.tool(name="ga4_get_data_retention", title="Get GA4 data retention", annotations=READ)
async def ga4_get_data_retention(property_id: PropertyId) -> dict[str, Any]:
    """Returns how long event- and user-level data is kept (affects explorations older than that)."""
    return await execute(
        _admin().properties().getDataRetentionSettings(name=f"{property_name(property_id)}/dataRetentionSettings")
    )


@mcp.tool(name="ga4_list_annotations", title="List GA4 annotations", annotations=READ)
async def ga4_list_annotations(property_id: PropertyId) -> dict[str, Any]:
    """Lists the notes shown on GA4 report charts (releases, campaigns, tracking changes)."""
    annotations = await collect(
        lambda token: _admin_alpha()
        .properties()
        .reportingDataAnnotations()
        .list(parent=property_name(property_id), pageSize=200, pageToken=token),
        "reportingDataAnnotations",
    )
    return {"annotations": annotations}


@mcp.tool(name="ga4_search_change_history", title="Search GA4 change history", annotations=READ)
async def ga4_search_change_history(
    account_id: Annotated[str, Field(description="GA4 account ID, e.g. '1234567' or 'accounts/1234567'.")],
    property_id: Annotated[str | None, Field(description="Limit to one property.")] = None,
    days: Annotated[int, Field(ge=1, le=730)] = 30,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Shows who changed what in GA4 settings recently. Needs a sign-in with write scopes."""
    account = str(account_id).strip().removeprefix("accounts/")
    if not account.isdigit():
        raise ToolError(f"'{account_id}' is not a GA4 account ID; see ga4_list_accounts.")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    body: dict[str, Any] = {
        "earliestChangeTime": since.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "pageSize": limit,
    }
    if property_id:
        body["property"] = property_name(property_id)
    response = await execute(
        _admin().accounts().searchChangeHistoryEvents(account=f"accounts/{account}", body=body)
    )
    return {"changes": response.get("changeHistoryEvents", [])}


# --- Write tools --------------------------------------------------------------


@mcp.tool(name="ga4_create_custom_dimension", title="Create GA4 custom dimension", annotations=CREATE)
async def ga4_create_custom_dimension(
    property_id: PropertyId,
    parameter_name: Annotated[
        str, Field(description="Event/user parameter to register, e.g. 'article_author'. Cannot be changed later.")
    ],
    display_name: Annotated[str, Field(description="Name shown in GA4 reports.")],
    scope: Literal["EVENT", "USER", "ITEM"] = "EVENT",
    description: str = "",
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Registers an event/user/item parameter as a custom dimension so it appears in reports."""
    body = drop_empty(
        {"parameterName": parameter_name, "displayName": display_name, "scope": scope, "description": description}
    )
    request = _admin().properties().customDimensions().create(parent=property_name(property_id), body=body)
    return await mutate("ga4_create_custom_dimension", request, dry_run=dry_run)


@mcp.tool(name="ga4_update_custom_dimension", title="Update GA4 custom dimension", annotations=CHANGE)
async def ga4_update_custom_dimension(
    name: Annotated[str, Field(description="e.g. 'properties/123/customDimensions/456'.")],
    display_name: str | None = None,
    description: str | None = None,
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Renames a custom dimension or changes its description (parameter and scope are fixed)."""
    body, mask = changed_fields(displayName=display_name, description=description)
    request = (
        _admin()
        .properties()
        .customDimensions()
        .patch(name=_child_name(name, "customDimensions"), updateMask=mask, body=body)
    )
    return await mutate("ga4_update_custom_dimension", request, dry_run=dry_run)


@mcp.tool(name="ga4_archive_custom_dimension", title="Archive GA4 custom dimension", annotations=CHANGE)
async def ga4_archive_custom_dimension(
    name: Annotated[str, Field(description="e.g. 'properties/123/customDimensions/456'.")],
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Archives a custom dimension. It disappears from reports and cannot be restored."""
    request = _admin().properties().customDimensions().archive(name=_child_name(name, "customDimensions"), body={})
    return await mutate("ga4_archive_custom_dimension", request, dry_run=dry_run)


@mcp.tool(name="ga4_create_custom_metric", title="Create GA4 custom metric", annotations=CREATE)
async def ga4_create_custom_metric(
    property_id: PropertyId,
    parameter_name: Annotated[str, Field(description="Numeric event parameter, e.g. 'video_percent'.")],
    display_name: str,
    measurement_unit: Literal[
        "STANDARD", "CURRENCY", "FEET", "METERS", "KILOMETERS", "MILES", "MILLISECONDS", "SECONDS", "MINUTES", "HOURS"
    ] = "STANDARD",
    description: str = "",
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Registers a numeric event parameter as a custom metric."""
    body = drop_empty(
        {
            "parameterName": parameter_name,
            "displayName": display_name,
            "measurementUnit": measurement_unit,
            "scope": "EVENT",
            "description": description,
        }
    )
    request = _admin().properties().customMetrics().create(parent=property_name(property_id), body=body)
    return await mutate("ga4_create_custom_metric", request, dry_run=dry_run)


@mcp.tool(name="ga4_archive_custom_metric", title="Archive GA4 custom metric", annotations=CHANGE)
async def ga4_archive_custom_metric(
    name: Annotated[str, Field(description="e.g. 'properties/123/customMetrics/456'.")],
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Archives a custom metric. It disappears from reports and cannot be restored."""
    request = _admin().properties().customMetrics().archive(name=_child_name(name, "customMetrics"), body={})
    return await mutate("ga4_archive_custom_metric", request, dry_run=dry_run)


@mcp.tool(name="ga4_create_key_event", title="Mark GA4 event as key event", annotations=CREATE)
async def ga4_create_key_event(
    property_id: PropertyId,
    event_name: Annotated[str, Field(description="Existing or future event name, e.g. 'generate_lead'.")],
    counting_method: Literal["ONCE_PER_EVENT", "ONCE_PER_SESSION"] = "ONCE_PER_EVENT",
    default_value: Annotated[float | None, Field(description="Optional default value when the event has none.")] = None,
    default_currency: Annotated[str | None, Field(description="ISO 4217 code for default_value, e.g. 'USD'.")] = None,
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Marks an event as a key event (conversion)."""
    body: dict[str, Any] = {"eventName": event_name, "countingMethod": counting_method}
    if default_value is not None:
        if not default_currency:
            raise ToolError("default_currency is required with default_value.")
        body["defaultValue"] = {"numericValue": default_value, "currencyCode": default_currency}
    request = _admin().properties().keyEvents().create(parent=property_name(property_id), body=body)
    return await mutate("ga4_create_key_event", request, dry_run=dry_run)


@mcp.tool(name="ga4_delete_key_event", title="Unmark GA4 key event", annotations=CHANGE)
async def ga4_delete_key_event(
    name: Annotated[str, Field(description="e.g. 'properties/123/keyEvents/456' from ga4_list_key_events.")],
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Stops counting an event as a key event. Past data is kept."""
    request = _admin().properties().keyEvents().delete(name=_child_name(name, "keyEvents"))
    return await mutate("ga4_delete_key_event", request, dry_run=dry_run)


Retention = Literal["TWO_MONTHS", "FOURTEEN_MONTHS", "TWENTY_SIX_MONTHS", "THIRTY_EIGHT_MONTHS", "FIFTY_MONTHS"]


@mcp.tool(name="ga4_update_data_retention", title="Change GA4 data retention", annotations=CHANGE)
async def ga4_update_data_retention(
    property_id: PropertyId,
    event_data_retention: Annotated[
        Retention | None, Field(description="Standard properties allow TWO_MONTHS or FOURTEEN_MONTHS.")
    ] = None,
    user_data_retention: Retention | None = None,
    reset_user_data_on_new_activity: bool | None = None,
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Changes how long GA4 keeps event- and user-level data."""
    body, mask = changed_fields(
        eventDataRetention=event_data_retention,
        userDataRetention=user_data_retention,
        resetUserDataOnNewActivity=reset_user_data_on_new_activity,
    )
    request = (
        _admin()
        .properties()
        .updateDataRetentionSettings(
            name=f"{property_name(property_id)}/dataRetentionSettings", updateMask=mask, body=body
        )
    )
    return await mutate("ga4_update_data_retention", request, dry_run=dry_run)


@mcp.tool(name="ga4_update_property", title="Update GA4 property settings", annotations=CHANGE)
async def ga4_update_property(
    property_id: PropertyId,
    display_name: str | None = None,
    time_zone: Annotated[str | None, Field(description="IANA name, e.g. 'Asia/Tehran'.")] = None,
    currency_code: Annotated[str | None, Field(description="ISO 4217, e.g. 'IRR' or 'USD'.")] = None,
    industry_category: Annotated[str | None, Field(description="e.g. 'SHOPPING', 'TECHNOLOGY'.")] = None,
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Changes a property's name, reporting time zone, currency or industry."""
    body, mask = changed_fields(
        displayName=display_name,
        timeZone=time_zone,
        currencyCode=currency_code,
        industryCategory=industry_category,
    )
    request = _admin().properties().patch(name=property_name(property_id), updateMask=mask, body=body)
    return await mutate("ga4_update_property", request, dry_run=dry_run)


def _date_parts(value: str) -> dict[str, int]:
    day = datetime.strptime(resolve_date(value), "%Y-%m-%d")
    return {"year": day.year, "month": day.month, "day": day.day}


@mcp.tool(name="ga4_create_annotation", title="Add GA4 annotation", annotations=CREATE)
async def ga4_create_annotation(
    property_id: PropertyId,
    title: Annotated[str, Field(max_length=150)],
    date: Annotated[str, Field(description="Day of the event: YYYY-MM-DD, 'today' or 'NdaysAgo'.")] = "today",
    end_date: Annotated[str | None, Field(description="Set to annotate a date range instead of one day.")] = None,
    description: str = "",
    color: Literal["PURPLE", "BROWN", "BLUE", "GREEN", "RED", "CYAN"] = "BLUE",
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Adds a note to GA4 report charts, e.g. 'GTM v12: fixed purchase tag'."""
    body: dict[str, Any] = drop_empty({"title": title, "description": description, "color": color})
    if end_date:
        body["annotationDateRange"] = {"startDate": _date_parts(date), "endDate": _date_parts(end_date)}
    else:
        body["annotationDate"] = _date_parts(date)
    request = (
        _admin_alpha().properties().reportingDataAnnotations().create(parent=property_name(property_id), body=body)
    )
    return await mutate("ga4_create_annotation", request, dry_run=dry_run)
