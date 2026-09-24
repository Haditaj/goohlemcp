"""Google Tag Manager: containers, workspaces, tags/triggers/variables, versions."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from goohle_mcp.app import CHANGE, CREATE, READ, mcp
from goohle_mcp.google_api import collect, execute, mutate, service
from goohle_mcp.tools.common import DryRun, drop_empty

# Workspace entity collections, named as in the API paths.
EntityType = Literal[
    "tags", "triggers", "variables", "folders", "templates", "clients", "transformations", "zones", "gtag_config"
]
_ENTITY_TYPES = EntityType.__args__
# Response keys differ from path segments for a few collections.
_LIST_KEYS = {"gtag_config": "gtagConfig"}

_ACCOUNT = r"accounts/\d+"
_CONTAINER = _ACCOUNT + r"/containers/\d+"
_WORKSPACE = _CONTAINER + r"/workspaces/\d+"
_ENTITY = re.compile(rf"({_WORKSPACE})/({'|'.join(_ENTITY_TYPES)})/[^/]+")
_VERSION = re.compile(rf"({_CONTAINER})/versions/\d+")

ContainerPath = Annotated[
    str, Field(description="Container path 'accounts/<id>/containers/<id>' from gtm_list_containers.")
]
WorkspacePath = Annotated[
    str,
    Field(description="Workspace path 'accounts/<id>/containers/<id>/workspaces/<id>' from gtm_list_workspaces."),
]
EntityPath = Annotated[
    str,
    Field(description="Entity path, e.g. 'accounts/1/containers/2/workspaces/3/tags/4', as returned by list tools."),
]

ENTITY_FORMAT_HINT = """\
Entities use the GTM API v2 resource format. Examples:
- GA4 event tag: {"name": "GA4 - generate_lead", "type": "gaawe", "firingTriggerId": ["12"],
  "parameter": [{"type": "template", "key": "eventName", "value": "generate_lead"},
                {"type": "template", "key": "measurementIdOverride", "value": "G-XXXXXXX"}]}
- Google tag: {"name": "Google tag", "type": "googtag", "firingTriggerId": ["2147479553"],
  "parameter": [{"type": "template", "key": "tagId", "value": "G-XXXXXXX"}]}
- Custom event trigger: {"name": "CE - form_submit", "type": "customEvent",
  "customEventFilter": [{"type": "equals", "parameter": [
      {"type": "template", "key": "arg0", "value": "{{_event}}"},
      {"type": "template", "key": "arg1", "value": "form_submit"}]}]}
- Data layer variable: {"name": "DLV - value", "type": "v",
  "parameter": [{"type": "integer", "key": "dataLayerVersion", "value": "2"},
                {"type": "template", "key": "name", "value": "ecommerce.value"}]}
Trigger 2147479553 is the built-in "All Pages". When unsure, read a similar existing
entity with gtm_get_entity and copy its structure."""


def _tagmanager() -> Any:
    return service("tagmanager", "v2")


def _containers() -> Any:
    return _tagmanager().accounts().containers()


def _workspaces() -> Any:
    return _containers().workspaces()


def _check(path: str, pattern: str, what: str) -> str:
    value = path.strip().strip("/")
    if not re.fullmatch(pattern, value):
        raise ToolError(f"'{path}' is not a GTM {what} path (expected {pattern.replace(chr(92) + 'd+', '<id>')}).")
    return value


def _account_path(account_id: str) -> str:
    value = str(account_id).strip()
    return _check(value if value.startswith("accounts/") else f"accounts/{value}", _ACCOUNT, "account")


def _entity(path: str) -> tuple[str, str]:
    match = _ENTITY.fullmatch(path.strip().strip("/"))
    if not match:
        raise ToolError(
            f"'{path}' is not a GTM entity path; expected "
            "'accounts/<id>/containers/<id>/workspaces/<id>/<type>/<id>' with type one of "
            f"{', '.join(_ENTITY_TYPES)}."
        )
    return match.group(0), match.group(2)


def _summary(entity: dict[str, Any]) -> dict[str, Any]:
    return drop_empty(
        {
            "path": entity.get("path"),
            "name": entity.get("name"),
            "type": entity.get("type"),
            "paused": entity.get("paused"),
            "firing_trigger_ids": entity.get("firingTriggerId"),
            "blocking_trigger_ids": entity.get("blockingTriggerId"),
            "folder_id": entity.get("parentFolderId"),
            "fingerprint": entity.get("fingerprint"),
        }
    )


# --- Read tools ---------------------------------------------------------------


@mcp.tool(name="gtm_list_accounts", title="List GTM accounts", annotations=READ)
async def gtm_list_accounts() -> dict[str, Any]:
    """Lists Tag Manager accounts the signed-in user can access."""
    accounts = await collect(lambda token: _tagmanager().accounts().list(pageToken=token), "account")
    return {"accounts": [{"path": a.get("path"), "name": a.get("name")} for a in accounts]}


@mcp.tool(name="gtm_list_containers", title="List GTM containers", annotations=READ)
async def gtm_list_containers(
    account_id: Annotated[str, Field(description="GTM account ID or 'accounts/<id>'.")],
) -> dict[str, Any]:
    """Lists containers in an account with their public GTM-XXXX IDs and domains."""
    parent = _account_path(account_id)
    containers = await collect(lambda token: _containers().list(parent=parent, pageToken=token), "container")
    return {
        "containers": [
            drop_empty(
                {
                    "path": c.get("path"),
                    "name": c.get("name"),
                    "public_id": c.get("publicId"),
                    "usage_context": c.get("usageContext"),
                    "domains": c.get("domainName"),
                }
            )
            for c in containers
        ]
    }


@mcp.tool(name="gtm_list_workspaces", title="List GTM workspaces", annotations=READ)
async def gtm_list_workspaces(container_path: ContainerPath) -> dict[str, Any]:
    """Lists workspaces (draft areas) in a container. Edits happen inside a workspace."""
    parent = _check(container_path, _CONTAINER, "container")
    workspaces = await collect(lambda token: _workspaces().list(parent=parent, pageToken=token), "workspace")
    return {
        "workspaces": [
            drop_empty({"path": w.get("path"), "name": w.get("name"), "description": w.get("description")})
            for w in workspaces
        ]
    }


@mcp.tool(name="gtm_list_entities", title="List GTM tags, triggers or variables", annotations=READ)
async def gtm_list_entities(
    workspace_path: WorkspacePath,
    entity_type: EntityType,
    summary: Annotated[
        bool, Field(description="True: name/type/triggers only. False: full definitions (can be large).")
    ] = True,
) -> dict[str, Any]:
    """Lists tags, triggers, variables, folders, custom templates, clients, transformations,
    zones or Google tag configs in a workspace."""
    parent = _check(workspace_path, _WORKSPACE, "workspace")
    resource = getattr(_workspaces(), entity_type)()
    items = await collect(
        lambda token: resource.list(parent=parent, pageToken=token), _LIST_KEYS.get(entity_type, entity_type[:-1])
    )
    return {entity_type: [_summary(i) for i in items] if summary else items}


@mcp.tool(name="gtm_list_built_in_variables", title="List enabled built-in variables", annotations=READ)
async def gtm_list_built_in_variables(workspace_path: WorkspacePath) -> dict[str, Any]:
    """Lists built-in variables (Page URL, Click Classes, ...) enabled in a workspace."""
    parent = _check(workspace_path, _WORKSPACE, "workspace")
    items = await collect(
        lambda token: _workspaces().built_in_variables().list(parent=parent, pageToken=token), "builtInVariable"
    )
    return {"built_in_variables": [{"name": v.get("name"), "type": v.get("type")} for v in items]}


@mcp.tool(name="gtm_get_entity", title="Get a GTM tag, trigger or variable", annotations=READ)
async def gtm_get_entity(path: EntityPath) -> dict[str, Any]:
    """Returns the full definition of one workspace entity, including its fingerprint."""
    entity_path, entity_type = _entity(path)
    return await execute(getattr(_workspaces(), entity_type)().get(path=entity_path))


@mcp.tool(name="gtm_get_workspace_status", title="Get GTM workspace changes", annotations=READ)
async def gtm_get_workspace_status(workspace_path: WorkspacePath) -> dict[str, Any]:
    """Shows what changed in a workspace compared with the latest version, and any merge conflicts."""
    path = _check(workspace_path, _WORKSPACE, "workspace")
    response = await execute(_workspaces().getStatus(path=path))
    changes = []
    for change in response.get("workspaceChange", []):
        kind = next((k for k in change if k != "changeStatus"), None)
        entity = change.get(kind, {}) if kind else {}
        changes.append({"status": change.get("changeStatus"), "kind": kind, "name": entity.get("name"), "path": entity.get("path")})
    return {"changes": changes, "merge_conflicts": response.get("mergeConflict", [])}


@mcp.tool(name="gtm_quick_preview", title="Compile-check a GTM workspace", annotations=READ)
async def gtm_quick_preview(workspace_path: WorkspacePath) -> dict[str, Any]:
    """Compiles the workspace without saving anything and reports compiler errors.

    Run before gtm_create_version. Needs a sign-in with write scopes.
    """
    path = _check(workspace_path, _WORKSPACE, "workspace")
    response = await execute(_workspaces().quick_preview(path=path))
    version = response.get("containerVersion", {})
    return {
        "compiler_error": bool(response.get("compilerError")),
        "sync_status": response.get("syncStatus"),
        "tag_count": len(version.get("tag", [])),
        "trigger_count": len(version.get("trigger", [])),
        "variable_count": len(version.get("variable", [])),
    }


@mcp.tool(name="gtm_list_versions", title="List GTM container versions", annotations=READ)
async def gtm_list_versions(container_path: ContainerPath) -> dict[str, Any]:
    """Lists container versions (newest last) and which one is live."""
    parent = _check(container_path, _CONTAINER, "container")
    headers = await collect(
        lambda token: _containers().version_headers().list(parent=parent, pageToken=token), "containerVersionHeader"
    )
    live = await execute(_containers().versions().live(parent=parent))
    return {
        "live_version_id": live.get("containerVersionId"),
        "versions": [
            drop_empty(
                {
                    "path": h.get("path"),
                    "version_id": h.get("containerVersionId"),
                    "name": h.get("name"),
                    "tags": h.get("numTags"),
                    "triggers": h.get("numTriggers"),
                    "variables": h.get("numVariables"),
                    "deleted": h.get("deleted"),
                }
            )
            for h in headers
        ],
    }


@mcp.tool(name="gtm_get_version", title="Get a GTM container version", annotations=READ)
async def gtm_get_version(
    container_path: ContainerPath,
    version_id: Annotated[str, Field(description="Version number, or 'live' for the published version.")] = "live",
    summary: Annotated[bool, Field(description="True: names/types only. False: full export.")] = True,
) -> dict[str, Any]:
    """Returns a container version: what exactly is (or was) live on the site."""
    parent = _check(container_path, _CONTAINER, "container")
    if version_id == "live":
        version = await execute(_containers().versions().live(parent=parent))
    else:
        if not str(version_id).isdigit():
            raise ToolError("version_id must be a number or 'live'.")
        version = await execute(_containers().versions().get(path=f"{parent}/versions/{version_id}"))
    if not summary:
        return version
    return drop_empty(
        {
            "path": version.get("path"),
            "version_id": version.get("containerVersionId"),
            "name": version.get("name"),
            "description": version.get("description"),
            "tags": [_summary(t) for t in version.get("tag", [])],
            "triggers": [_summary(t) for t in version.get("trigger", [])],
            "variables": [_summary(v) for v in version.get("variable", [])],
            "built_in_variables": [v.get("type") for v in version.get("builtInVariable", [])],
        }
    )


# --- Write tools --------------------------------------------------------------


@mcp.tool(name="gtm_create_workspace", title="Create GTM workspace", annotations=CREATE)
async def gtm_create_workspace(
    container_path: ContainerPath,
    name: str,
    description: str = "",
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Creates a new workspace so changes stay separate from other drafts."""
    parent = _check(container_path, _CONTAINER, "container")
    request = _workspaces().create(parent=parent, body=drop_empty({"name": name, "description": description}))
    return await mutate("gtm_create_workspace", request, dry_run=dry_run)


@mcp.tool(
    name="gtm_create_entity",
    title="Create GTM tag, trigger or variable",
    description=(
        "Creates a tag, trigger, variable, folder, template, client, transformation, zone or "
        "Google tag config in a workspace. Not live until a version is created and published.\n\n"
        + ENTITY_FORMAT_HINT
    ),
    annotations=CREATE,
)
async def gtm_create_entity(
    workspace_path: WorkspacePath,
    entity_type: EntityType,
    entity: Annotated[dict[str, Any], Field(description="The resource body in GTM API v2 format (see examples).")],
    dry_run: DryRun = False,
) -> dict[str, Any]:
    parent = _check(workspace_path, _WORKSPACE, "workspace")
    request = getattr(_workspaces(), entity_type)().create(parent=parent, body=entity)
    return await mutate("gtm_create_entity", request, dry_run=dry_run)


@mcp.tool(name="gtm_update_entity", title="Update GTM tag, trigger or variable", annotations=CHANGE)
async def gtm_update_entity(
    path: EntityPath,
    changes: Annotated[
        dict[str, Any],
        Field(
            description=(
                "Top-level fields to replace, e.g. {'paused': true} or {'firingTriggerId': ['12']}. "
                "List fields such as 'parameter' are replaced whole, so send the complete list."
            )
        ),
    ],
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Changes fields of an existing workspace entity.

    The current definition is fetched and merged with `changes`, and its fingerprint is
    sent so the update fails instead of overwriting someone else's newer edit.
    """
    entity_path, entity_type = _entity(path)
    resource = getattr(_workspaces(), entity_type)()
    current = await execute(resource.get(path=entity_path))
    merged = {**current, **changes}
    request = resource.update(path=entity_path, fingerprint=current.get("fingerprint"), body=merged)
    return await mutate("gtm_update_entity", request, dry_run=dry_run)


@mcp.tool(name="gtm_delete_entity", title="Delete GTM tag, trigger or variable", annotations=CHANGE)
async def gtm_delete_entity(path: EntityPath, dry_run: DryRun = False) -> dict[str, Any]:
    """Deletes an entity from the workspace (recoverable with gtm_revert_entity until a version is created)."""
    entity_path, entity_type = _entity(path)
    request = getattr(_workspaces(), entity_type)().delete(path=entity_path)
    return await mutate("gtm_delete_entity", request, dry_run=dry_run)


@mcp.tool(name="gtm_revert_entity", title="Revert GTM workspace change", annotations=CHANGE)
async def gtm_revert_entity(path: EntityPath, dry_run: DryRun = False) -> dict[str, Any]:
    """Undoes this workspace's changes to one entity, restoring the latest version's definition."""
    entity_path, entity_type = _entity(path)
    request = getattr(_workspaces(), entity_type)().revert(path=entity_path)
    return await mutate("gtm_revert_entity", request, dry_run=dry_run)


@mcp.tool(name="gtm_set_built_in_variables", title="Enable or disable built-in variables", annotations=CHANGE)
async def gtm_set_built_in_variables(
    workspace_path: WorkspacePath,
    types: Annotated[
        list[str],
        Field(min_length=1, description="Built-in variable types, e.g. ['clickText', 'clickUrl', 'formId', 'pageUrl']."),
    ],
    enabled: bool = True,
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Turns built-in variables on or off in a workspace."""
    parent = _check(workspace_path, _WORKSPACE, "workspace")
    resource = _workspaces().built_in_variables()
    request = resource.create(parent=parent, type=types) if enabled else resource.delete(path=parent, type=types)
    return await mutate("gtm_set_built_in_variables", request, dry_run=dry_run)


@mcp.tool(name="gtm_create_version", title="Create GTM version from workspace", annotations=CREATE)
async def gtm_create_version(
    workspace_path: WorkspacePath,
    name: Annotated[str, Field(description="Short version name, e.g. 'Add generate_lead tag'.")],
    notes: Annotated[str, Field(description="What changed and why.")] = "",
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Saves the workspace as a new container version (not yet live).

    GTM consumes the workspace in the process. Publish the result with gtm_publish_version.
    """
    path = _check(workspace_path, _WORKSPACE, "workspace")
    request = _workspaces().create_version(path=path, body=drop_empty({"name": name, "notes": notes}))
    response = await mutate("gtm_create_version", request, dry_run=dry_run)
    if dry_run or not isinstance(response, dict):
        return response
    version = response.get("containerVersion", {})
    return drop_empty(
        {
            "compiler_error": bool(response.get("compilerError")),
            "version_path": version.get("path"),
            "version_id": version.get("containerVersionId"),
            "name": version.get("name"),
            "new_workspace_path": response.get("newWorkspacePath"),
            "sync_status": response.get("syncStatus"),
        }
    )


@mcp.tool(name="gtm_publish_version", title="Publish GTM version (goes live)", annotations=CHANGE)
async def gtm_publish_version(
    version_path: Annotated[str, Field(description="'accounts/<id>/containers/<id>/versions/<id>'.")],
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Publishes a container version to the live website. Requires GOOHLE_MCP_MODE=publish.

    Only call after the user explicitly approved publishing this exact version.
    Roll back by publishing the previous version from gtm_list_versions.
    """
    path = version_path.strip().strip("/")
    if not _VERSION.fullmatch(path):
        raise ToolError(f"'{version_path}' is not a GTM version path.")
    request = _containers().versions().publish(path=path)
    response = await mutate("gtm_publish_version", request, dry_run=dry_run, level="publish")
    if dry_run or not isinstance(response, dict):
        return response
    version = response.get("containerVersion", {})
    return {
        "compiler_error": bool(response.get("compilerError")),
        "published_version_id": version.get("containerVersionId"),
        "name": version.get("name"),
    }
