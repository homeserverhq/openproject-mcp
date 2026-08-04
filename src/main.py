"""OpenProject MCP server entry point."""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any, Optional

from fastmcp import FastMCP

from mcp.types import ToolAnnotations

from toon_mcp import json_to_toon

from src.client import OpenProjectClient, ALLOW_ALL_AGGREGATE

MCP_SERVER_PORT = int(os.environ.get("MCP_SERVER_PORT", "6893"))
IS_STATEFUL = os.getenv("IS_STATEFUL", "false").lower() in ("true", "1", "yes")

# ─── Auth passthrough (multi-tenant) ──────────────────────────────────

_current_user_token: ContextVar[Optional[str]] = ContextVar("current_user_token", default=None)

_client: OpenProjectClient | None = None


def get_client() -> OpenProjectClient:
    global _client
    if _client is None:
        _client = OpenProjectClient()
    return _client


def get_user_token() -> Optional[str]:
    return _current_user_token.get()


class AuthMiddleware:
    """ASGI middleware that extracts Bearer token from incoming HTTP request and stores it in context var."""
    def __init__(self, app):
        self.app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode()
            if auth_header.startswith("Bearer "):
                _current_user_token.set(auth_header[7:])
        await self.app(scope, receive, send)


# ─── FastMCP instance ─────────────────────────────────────────────────

mcp = FastMCP("OpenProject MCP Server")


# ─── Pydantic contract models ─────────────────────────────────────────

from pydantic import BaseModel, Field


class WPCreate(BaseModel):
    subject: str = Field(description="Title of the work package")
    project_id: int = Field(description="ID of the project this work package belongs to")
    type_id: int = Field(description="ID of the type (e.g. Task, Milestone)")
    description: str = Field(default="", description="Description text (supports markdown mentions like @user#ID)")
    status_id: int | None = Field(default=None, description="ID of the status (e.g. New, In Progress)")
    priority_id: int | None = Field(default=None, description="ID of the priority (e.g. High, Normal)")
    assignee_id: int | None = Field(default=None, description="ID of the user assigned to this work package")
    responsible_id: int | None = Field(default=None, description="ID of the user responsible for this work package")
    version_id: int | None = Field(default=None, description="ID of the version this work package belongs to")
    parent_id: int | None = Field(default=None, description="ID of the parent work package for hierarchy")
    start_date: str | None = Field(default=None, description="Date in YYYY-MM-DD format (2026-12-31)")
    due_date: str | None = Field(default=None, description="Date in YYYY-MM-DD format (2026-12-31)")
    estimated_time: str | None = Field(default=None, description="Estimated time in ISO 8601 duration format (e.g. PT4H)")
    duration: str | None = Field(default=None, description="Duration in ISO 8601 format (e.g. P3D for 3 days)")
    schedule_manually: bool = Field(default=False, description="true or false")
    ignore_non_working_days: bool = Field(default=False, description="true or false")
    category_id: int | None = Field(default=None, description="ID of the category")


class WPUpdate(BaseModel):
    subject: str | None = Field(default=None, description="Title of the work package")
    description: str | None = Field(default=None, description="Description text (supports markdown mentions)")
    status_id: int | None = Field(default=None, description="ID of the status (e.g. New, In Progress)")
    priority_id: int | None = Field(default=None, description="ID of the priority (e.g. High, Normal)")
    assignee_id: int | None = Field(default=None, description="ID of the assigned user")
    responsible_id: int | None = Field(default=None, description="ID of the responsible user")
    version_id: int | None = Field(default=None, description="ID of the version")
    parent_id: int | None = Field(default=None, description="ID of the parent work package")
    start_date: str | None = Field(default=None, description="Date in YYYY-MM-DD format (2026-12-31)")
    due_date: str | None = Field(default=None, description="Date in YYYY-MM-DD format (2026-12-31)")
    estimated_time: str | None = Field(default=None, description="Estimated time in ISO 8601 format (e.g. PT4H)")
    duration: str | None = Field(default=None, description="Duration in ISO 8601 format (e.g. P3D)")
    schedule_manually: bool | None = Field(default=None, description="true or false")
    ignore_non_working_days: bool | None = Field(default=None, description="true or false")
    percentage_done: int | None = Field(default=None, description="Completion percentage (0-100)")
    lock_version: int | None = Field(default=None, description="Lock version for optimistic locking")


class ProjectCreate(BaseModel):
    name: str = Field(description="Project name")
    identifier: str = Field(description="Unique URL-safe project identifier")
    description: str = Field(default="", description="Project description")
    public: bool = Field(default=True, description="true or false (Default: true)")
    active: bool = Field(default=True, description="true or false (Default: true)")
    status_id: str | None = Field(default=None, description="Project status: on_track, at_risk, off_track, not_started, finished, or discontinued")
    parent_id: int | None = Field(default=None, description="ID of the parent project")
    status_explanation: str = Field(default="", description="Explanation of the project status")


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, description="Project name")
    description: str | None = Field(default=None, description="Project description")
    public: bool | None = Field(default=None, description="true or false")
    active: bool | None = Field(default=None, description="true or false")
    status_id: str | None = Field(default=None, description="Project status: on_track, at_risk, off_track, not_started, finished, or discontinued")
    parent_id: int | None = Field(default=None, description="ID of the parent project")
    status_explanation: str | None = Field(default=None, description="Explanation of the project status")
    lock_version: int | None = Field(default=None, description="Lock version for optimistic locking")


class VersionCreate(BaseModel):
    name: str = Field(description="Version name")
    project_id: int = Field(description="ID of the project this version belongs to")
    description: str = Field(default="", description="Version description")
    status: str = Field(default="open", description="Status: open, locked, or closed (Default: open)")
    sharing: str = Field(default="none", description="Sharing mode: none, descendants, hierarchy, tree, or system (Default: none)")
    start_date: str | None = Field(default=None, description="Date in YYYY-MM-DD format (2026-12-31)")
    end_date: str | None = Field(default=None, description="Date in YYYY-MM-DD format (2026-12-31)")


class VersionUpdate(BaseModel):
    name: str | None = Field(default=None, description="Version name")
    description: str | None = Field(default=None, description="Version description")
    status: str | None = Field(default=None, description="Status: open, locked, or closed")
    sharing: str | None = Field(default=None, description="Sharing mode: none, descendants, hierarchy, tree, or system")
    start_date: str | None = Field(default=None, description="Date in YYYY-MM-DD format (2026-12-31)")
    end_date: str | None = Field(default=None, description="Date in YYYY-MM-DD format (2026-12-31)")
    lock_version: int | None = Field(default=None, description="Lock version for optimistic locking")


class MembershipCreate(BaseModel):
    project_id: int = Field(description="ID of the project")
    principal_id: int = Field(description="ID of the user or group to add as member")
    role_ids: list[int] = Field(description="List of role IDs to assign to the member")


class MembershipUpdate(BaseModel):
    project_id: int | None = Field(default=None, description="ID of the project")
    principal_id: int | None = Field(default=None, description="ID of the user or group")
    role_ids: list[int] | None = Field(default=None, description="List of role IDs to assign")
    lock_version: int | None = Field(default=None, description="Lock version for optimistic locking")


class MeetingCreate(BaseModel):
    title: str = Field(description="Meeting title")
    project_id: int = Field(description="ID of the project this meeting belongs to")
    start_time: str = Field(description="ISO 8601 format (2026-06-22T15:00:00-04:00)")
    end_time: str = Field(description="ISO 8601 format (2026-06-22T16:00:00-04:00)")
    location: str = Field(default="", description="Meeting location or video call link")
    notify: bool = Field(default=True, description="true or false (Default: true)")


class MeetingUpdate(BaseModel):
    title: str | None = Field(default=None, description="Meeting title")
    start_time: str | None = Field(default=None, description="ISO 8601 format (2026-06-22T15:00:00-04:00)")
    end_time: str | None = Field(default=None, description="ISO 8601 format (2026-06-22T16:00:00-04:00)")
    location: str | None = Field(default=None, description="Meeting location or video call link")
    notify: bool | None = Field(default=None, description="true or false")
    lock_version: int | None = Field(default=None, description="Lock version for optimistic locking")


class TimeEntryCreate(BaseModel):
    project_id: int = Field(description="ID of the project")
    work_package_id: int | None = Field(default=None, description="ID of the work package this time is logged against")
    user_id: int | None = Field(default=None, description="ID of the user who performed the work")
    activity_id: int | None = Field(default=None, description="ID of the activity type (e.g. Management, Development, Testing)")
    hours: str = Field(description="Time spent in ISO 8601 duration format (e.g. PT2H30M)")
    spent_on: str | None = Field(default=None, description="Date in YYYY-MM-DD format (2026-12-31)")
    comment: str = Field(default="", description="Comment describing the work done")


class TimeEntryUpdate(BaseModel):
    project_id: int | None = Field(default=None, description="ID of the project")
    work_package_id: int | None = Field(default=None, description="ID of the work package")
    hours: str | None = Field(default=None, description="Time spent in ISO 8601 duration format (e.g. PT2H30M)")
    spent_on: str | None = Field(default=None, description="Date in YYYY-MM-DD format (2026-12-31)")
    comment: str | None = Field(default=None, description="Comment describing the work done")
    lock_version: int | None = Field(default=None, description="Lock version for optimistic locking")


class NewsCreate(BaseModel):
    project_id: int = Field(description="ID of the project this news belongs to")
    title: str = Field(description="News title")
    summary: str = Field(default="", description="Short summary of the news")
    description: str = Field(default="", description="Full news content in markdown format")


class NewsUpdate(BaseModel):
    title: str | None = Field(default=None, description="News title")
    summary: str | None = Field(default=None, description="Short summary of the news")
    description: str | None = Field(default=None, description="Full news content in markdown format")
    lock_version: int | None = Field(default=None, description="Lock version for optimistic locking")


class GridCreate(BaseModel):
    page: str = Field(description="Page identifier (e.g. overview, project-overview, my_page)")
    row_count: int = Field(default=5, description="Number of rows in the grid (Default: 5)")


class GridUpdate(BaseModel):
    page: str | None = Field(default=None, description="Page identifier (e.g. overview, project-overview, my_page)")
    row_count: int | None = Field(default=None, description="Number of rows in the grid")
    lock_version: int | None = Field(default=None, description="Lock version for optimistic locking")


class GridWidget(BaseModel):
    row: int = Field(description="Row position (1-indexed)")
    column: int = Field(description="Column position (1-indexed)")
    identifier: str = Field(description="Widget type: work_packages_table, work_packages_graph, work_packages_calendar, project_description, project_status, subprojects, time_entries_list, members, news, documents, or custom_text")
    start_row: int | None = Field(default=None, description="Start row for widget span")
    end_row: int | None = Field(default=None, description="End row for widget span")
    start_column: int | None = Field(default=None, description="Start column for widget span")
    end_column: int | None = Field(default=None, description="End column for widget span")


class FilterCondition(BaseModel):
    field: str = Field(description="Field name to filter on (e.g. status_id, project_id, type_id, name, email)")
    operator: str = Field(description="Operator: equals, not, gte, lte, date_range, any, contains, or not_contains")
    values: list[str] = Field(description="Filter values as strings (single or multiple)")


class FilterExpression(BaseModel):
    conditions: list[FilterCondition] = Field(description="List of filter conditions to apply")


_DAY_NAMES: dict[str, int] = {
    "monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4,
    "friday": 5, "saturday": 6, "sunday": 7,
}

_OPERATOR_MAP: dict[str, str] = {
    "equals": "=", "not": "!", "gte": ">=", "lte": "<=",
    "date_range": "<>d", "any": "**", "contains": "~", "not_contains": "!~",
}


# ─── Helper ───────────────────────────────────────────────────────────

def _build_wp_payload(data: WPCreate) -> dict[str, Any]:
    links: dict[str, Any] = {
        "project": {"href": f"/api/v3/projects/{data.project_id}"},
        "type": {"href": f"/api/v3/types/{data.type_id}"},
    }
    if data.status_id is not None:
        links["status"] = {"href": f"/api/v3/statuses/{data.status_id}"}
    if data.priority_id is not None:
        links["priority"] = {"href": f"/api/v3/priorities/{data.priority_id}"}
    if data.assignee_id is not None:
        links["assignee"] = {"href": f"/api/v3/users/{data.assignee_id}"}
    if data.responsible_id is not None:
        links["responsible"] = {"href": f"/api/v3/users/{data.responsible_id}"}
    if data.version_id is not None:
        links["version"] = {"href": f"/api/v3/versions/{data.version_id}"}
    if data.parent_id is not None:
        links["parent"] = {"href": f"/api/v3/work_packages/{data.parent_id}"}
    if data.category_id is not None:
        links["category"] = {"href": f"/api/v3/categories/{data.category_id}"}
    payload: dict[str, Any] = {
        "subject": data.subject,
        "_links": links,
    }
    if data.description:
        payload["description"] = {"format": "markdown", "raw": data.description}
    if data.start_date:
        payload["startDate"] = data.start_date
    if data.due_date:
        payload["dueDate"] = data.due_date
    if data.estimated_time:
        payload["estimatedTime"] = data.estimated_time
    if data.duration:
        payload["duration"] = data.duration
    if data.schedule_manually:
        payload["scheduleManually"] = data.schedule_manually
    if data.ignore_non_working_days:
        payload["ignoreNonWorkingDays"] = data.ignore_non_working_days
    return payload


def _build_membership_payload(data: MembershipCreate) -> dict[str, Any]:
    return {
        "_links": {
            "project": {"href": f"/api/v3/projects/{data.project_id}"},
            "principal": {"href": f"/api/v3/users/{data.principal_id}"},
            "roles": [{"href": f"/api/v3/roles/{rid}"} for rid in data.role_ids],
        }
    }


def _build_filter_string(expr: FilterExpression | None) -> str | None:
    if expr is None or not expr.conditions:
        return None
    filters_list: list[dict[str, Any]] = []
    for c in expr.conditions:
        filters_list.append({c.field: {"operator": _OPERATOR_MAP.get(c.operator, c.operator), "values": c.values}})
    import json as _json
    return _json.dumps(filters_list)


def _build_widgets_payload(widgets: list[GridWidget]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for w in widgets:
        item: dict[str, Any] = {
            "row": w.row,
            "column": w.column,
            "identifier": w.identifier,
        }
        if w.start_row is not None:
            item["startRow"] = w.start_row
        if w.end_row is not None:
            item["endRow"] = w.end_row
        if w.start_column is not None:
            item["startColumn"] = w.start_column
        if w.end_column is not None:
            item["endColumn"] = w.end_column
        result.append(item)
    return result


# ─── Work Package Tools ───────────────────────────────────────────────

@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="List Work Packages", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_work_packages(
    page_size: int = 20,
    offset: int = 1,
    project_id: int | None = None,
    status_id: int | None = None,
    type_id: int | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List work packages (paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        project_id: ID of the project.
        status_id: ID of the status.
        type_id: ID of the type.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    filters: list[dict[str, Any]] = []
    if project_id is not None:
        filters.append({"project": {"operator": "=", "values": [str(project_id)]}})
    if status_id is not None:
        filters.append({"status": {"operator": "=", "values": [str(status_id)]}})
    if type_id is not None:
        filters.append({"type": {"operator": "=", "values": [str(type_id)]}})
    filter_str = None
    if filters:
        import json as _json
        filter_str = _json.dumps(filters)
    data = get_client().list_work_packages(token, 
        page_size=page_size, offset=offset, filters=filter_str,
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Create Work Package", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def create_work_package(
    subject: str,
    project_id: int,
    type_id: int,
    description: str = "",
    status_id: int | None = None,
    priority_id: int | None = None,
    assignee_id: int | None = None,
    responsible_id: int | None = None,
    version_id: int | None = None,
    parent_id: int | None = None,
    start_date: str | None = None,
    due_date: str | None = None,
    estimated_time: str | None = None,
    duration: str | None = None,
    schedule_manually: bool = False,
    ignore_non_working_days: bool = False,
    category_id: int | None = None,
) -> dict[str, Any]:
    """Create a work package.

    Args:
        subject: Subject or title.
        project_id: ID of the project.
        type_id: ID of the type.
        description: Description text in markdown format.
        status_id: ID of the status.
        priority_id: ID of the priority.
        assignee_id: ID of the assigned user.
        responsible_id: ID of the responsible user.
        version_id: ID of the version.
        parent_id: ID of the parent work package.
        start_date: Date in YYYY-MM-DD format (2026-12-31).
        due_date: Date in YYYY-MM-DD format (2026-12-31).
        estimated_time: Estimated time in ISO 8601 duration format (e.g. PT4H).
        duration: Duration in ISO 8601 format (e.g. P3D).
        schedule_manually: true or false.
        ignore_non_working_days: true or false.
        category_id: ID of the category.
    """
    token = get_user_token()
    data = WPCreate(
        subject=subject, project_id=project_id, type_id=type_id,
        description=description, status_id=status_id, priority_id=priority_id,
        assignee_id=assignee_id, responsible_id=responsible_id,
        version_id=version_id, parent_id=parent_id, start_date=start_date,
        due_date=due_date, estimated_time=estimated_time, duration=duration,
        schedule_manually=schedule_manually,
        ignore_non_working_days=ignore_non_working_days, category_id=category_id,
    )
    return get_client().create_work_package(token, _build_wp_payload(data), ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="Get Work Package By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_work_package_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single work package by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_work_package_by_id(token, id, include_all_fields=include_all_fields)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Update Work Package", readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def update_work_package(
    id: int,
    subject: str | None = None,
    description: str | None = None,
    status_id: int | None = None,
    priority_id: int | None = None,
    assignee_id: int | None = None,
    responsible_id: int | None = None,
    version_id: int | None = None,
    parent_id: int | None = None,
    start_date: str | None = None,
    due_date: str | None = None,
    estimated_time: str | None = None,
    duration: str | None = None,
    schedule_manually: bool | None = None,
    ignore_non_working_days: bool | None = None,
    percentage_done: int | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a work package.

    Args:
        id: ID of the resource.
        subject: Subject or title.
        description: Description text in markdown format.
        status_id: ID of the status.
        priority_id: ID of the priority.
        assignee_id: ID of the assigned user.
        responsible_id: ID of the responsible user.
        version_id: ID of the version.
        parent_id: ID of the parent work package.
        start_date: Date in YYYY-MM-DD format (2026-12-31).
        due_date: Date in YYYY-MM-DD format (2026-12-31).
        estimated_time: Estimated time in ISO 8601 duration format (e.g. PT4H).
        duration: Duration in ISO 8601 format (e.g. P3D).
        schedule_manually: true or false.
        ignore_non_working_days: true or false.
        percentage_done: Completion percentage (0-100).
        lock_version: Lock version for optimistic locking.
    """
    token = get_user_token()
    payload: dict[str, Any] = {}
    if subject is not None:
        payload["subject"] = subject
    if description is not None:
        payload["description"] = {"format": "markdown", "raw": description}
    if status_id is not None:
        payload["_links"] = payload.get("_links", {})
        payload["_links"]["status"] = {"href": f"/api/v3/statuses/{status_id}"}
    if priority_id is not None:
        payload.setdefault("_links", {})["priority"] = {"href": f"/api/v3/priorities/{priority_id}"}
    if assignee_id is not None:
        payload.setdefault("_links", {})["assignee"] = {"href": f"/api/v3/users/{assignee_id}"}
    if responsible_id is not None:
        payload.setdefault("_links", {})["responsible"] = {"href": f"/api/v3/users/{responsible_id}"}
    if version_id is not None:
        payload.setdefault("_links", {})["version"] = {"href": f"/api/v3/versions/{version_id}"}
    if parent_id is not None:
        payload.setdefault("_links", {})["parent"] = {"href": f"/api/v3/work_packages/{parent_id}"}
    if start_date is not None:
        payload["startDate"] = start_date
    if due_date is not None:
        payload["dueDate"] = due_date
    if estimated_time is not None:
        payload["estimatedTime"] = estimated_time
    if duration is not None:
        payload["duration"] = duration
    if schedule_manually is not None:
        payload["scheduleManually"] = schedule_manually
    if ignore_non_working_days is not None:
        payload["ignoreNonWorkingDays"] = ignore_non_working_days
    if percentage_done is not None:
        payload["percentageDone"] = percentage_done
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_work_package(token, id, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Delete Work Package", readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
)
def delete_work_package(id: int) -> dict[str, Any]:
    """Delete a work package.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().delete_work_package(token, id)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Get Work Package Activities", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_work_package_activities(
    id: int,
    page_size: int = 20,
    offset: int = 1,
) -> dict[str, Any]:
    """List activities (comments/journal entries) on a work package.

    Args:
        id: ID of the resource.
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
    """
    token = get_user_token()
    return get_client().get_work_package_activities(token, id, page_size, offset)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Add Work Package Comment", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def add_work_package_comment(id: int, comment: str) -> dict[str, Any]:
    """Add a comment to a work package.

    Args:
        id: ID of the resource.
        comment: Comment text.
    """
    token = get_user_token()
    return get_client().add_work_package_comment(token, id, comment)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Get Work Package Relations", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_work_package_relations(id: int) -> dict[str, Any]:
    """List relations for a work package.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_work_package_relations(token, id)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Create Work Package Relation", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def create_work_package_relation(
    id: int,
    target_id: int,
    relation_type: str = "relates",
) -> dict[str, Any]:
    """Create a relation from a work package to another.

    Args:
        id: ID of the resource.
        target_id: ID of the target work package for the relation.
        relation_type: relates, precedes, follows, blocks, blocked, duplicates, duplicated, includes, partof, requires, required, parent, or child (Default: relates).
    """
    token = get_user_token()
    return get_client().create_work_package_relation(token, 
        id,
        {"_links": {"to": {"href": f"/api/v3/work_packages/{target_id}"}}, "type": relation_type},
    )


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Get Work Package Watchers", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_work_package_watchers(id: int) -> dict[str, Any]:
    """List watchers of a work package.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_work_package_watchers(token, id)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Add Work Package Watcher", readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def add_work_package_watcher(id: int, user_id: int) -> dict[str, Any]:
    """Add a watcher to a work package.

    Args:
        id: ID of the resource.
        user_id: ID of the user.
    """
    token = get_user_token()
    return get_client().add_work_package_watcher(token, id, user_id)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Remove Work Package Watcher", readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
)
def remove_work_package_watcher(id: int, user_id: int) -> dict[str, Any]:
    """Remove a watcher from a work package.

    Args:
        id: ID of the resource.
        user_id: ID of the user.
    """
    token = get_user_token()
    return get_client().remove_work_package_watcher(token, id, user_id)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="List Work Package Attachments", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_work_package_attachments(
    id: int,
    page_size: int = 20,
    offset: int = 1,
) -> dict[str, Any]:
    """List attachment metadata for a work package.

    Args:
        id: ID of the resource.
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
    """
    token = get_user_token()
    data = get_client().list_work_package_attachments(token, id, page_size, offset)
    return {"items": json_to_toon(data)}
# ─── Project Tools ────────────────────────────────────────────────────

@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="List Projects", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_projects(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List projects (paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    data = get_client().list_projects(token, 
        page_size=page_size, offset=offset, include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="Create Project", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def create_project(
    name: str,
    identifier: str,
    description: str = "",
    public: bool = True,
    active: bool = True,
    status_id: str | None = None,
    parent_id: int | None = None,
    status_explanation: str = "",
) -> dict[str, Any]:
    """Create a project.

    Args:
        name: Name.
        identifier: Unique URL-safe identifier.
        description: Description text in markdown format.
        public: true or false (Default: true).
        active: true or false (Default: true).
        status_id: ID of the status.
        parent_id: ID of the parent work package.
        status_explanation: Explanation of the project status.
    """
    token = get_user_token()
    links: dict[str, Any] = {}
    if parent_id is not None:
        links["parent"] = {"href": f"/api/v3/projects/{parent_id}"}
    if status_id is not None:
        links["status"] = {"href": f"/api/v3/project_statuses/{status_id}"}
    payload: dict[str, Any] = {
        "name": name,
        "identifier": identifier,
        "public": public,
        "active": active,
        "_links": links,
    }
    if description:
        payload["description"] = {"format": "markdown", "raw": description}
    if status_explanation:
        payload["statusExplanation"] = {"format": "markdown", "raw": status_explanation}
    return get_client().create_project(token, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="Get Project By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_project_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single project by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_project_by_id(token, id, include_all_fields=include_all_fields)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Update Project", readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def update_project(
    id: int,
    name: str | None = None,
    description: str | None = None,
    public: bool | None = None,
    active: bool | None = None,
    status_id: str | None = None,
    parent_id: int | None = None,
    status_explanation: str | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a project.

    Args:
        id: ID of the resource.
        name: Name.
        description: Description text in markdown format.
        public: true or false.
        active: true or false.
        status_id: ID of the status.
        parent_id: ID of the parent work package.
        status_explanation: Explanation of the project status.
        lock_version: Lock version for optimistic locking.
    """
    token = get_user_token()
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if description is not None:
        payload["description"] = {"format": "markdown", "raw": description}
    if public is not None:
        payload["public"] = public
    if active is not None:
        payload["active"] = active
    if status_id is not None:
        payload.setdefault("_links", {})["status"] = {"href": f"/api/v3/project_statuses/{status_id}"}
    if parent_id is not None:
        payload.setdefault("_links", {})["parent"] = {"href": f"/api/v3/projects/{parent_id}"}
    if status_explanation is not None:
        payload["statusExplanation"] = {"format": "markdown", "raw": status_explanation}
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_project(token, id, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Delete Project", readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
)
def delete_project(id: int) -> dict[str, Any]:
    """Delete a project.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().delete_project(token, id)


@mcp.tool(
    tags={"advanced", "openproject"}, annotations=ToolAnnotations(title="Copy Project", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def copy_project(
    id: int,
    name: str | None = None,
    identifier: str | None = None,
) -> dict[str, Any]:
    """Copy a project.

    Args:
        id: ID of the resource.
        name: Name.
        identifier: Unique URL-safe identifier.
    """
    token = get_user_token()
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if identifier is not None:
        payload["identifier"] = identifier
    return get_client().copy_project(token, id, payload)


# ─── Version Tools ────────────────────────────────────────────────────

@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="List Versions", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_versions(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List versions (paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    data = get_client().list_versions(token, 
        page_size=page_size, offset=offset, include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Create Version", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def create_version(
    name: str,
    project_id: int,
    description: str = "",
    status: str = "open",
    sharing: str = "none",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Create a version.

    Args:
        name: Name.
        project_id: ID of the project.
        description: Description text in markdown format.
        status: Status: open, locked, or closed (Default: open).
        sharing: Sharing mode: none, descendants, hierarchy, tree, or system (Default: none).
        start_date: Date in YYYY-MM-DD format (2026-12-31).
        end_date: Date in YYYY-MM-DD format (2026-12-31).
    """
    token = get_user_token()
    payload: dict[str, Any] = {
        "name": name,
        "_links": {"definingProject": {"href": f"/api/v3/projects/{project_id}"}},
        "status": status,
        "sharing": sharing,
    }
    if description:
        payload["description"] = {"format": "markdown", "raw": description}
    if start_date:
        payload["startDate"] = start_date
    if end_date:
        payload["endDate"] = end_date
    return get_client().create_version(token, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="Get Version By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_version_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single version by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_version_by_id(token, id, include_all_fields=include_all_fields)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Update Version", readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def update_version(
    id: int,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    sharing: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a version.

    Args:
        id: ID of the resource.
        name: Name.
        description: Description text in markdown format.
        status: Status: open, locked, or closed.
        sharing: Sharing mode: none, descendants, hierarchy, tree, or system.
        start_date: Date in YYYY-MM-DD format (2026-12-31).
        end_date: Date in YYYY-MM-DD format (2026-12-31).
        lock_version: Lock version for optimistic locking.
    """
    token = get_user_token()
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if description is not None:
        payload["description"] = {"format": "markdown", "raw": description}
    if status is not None:
        payload["status"] = status
    if sharing is not None:
        payload["sharing"] = sharing
    if start_date is not None:
        payload["startDate"] = start_date
    if end_date is not None:
        payload["endDate"] = end_date
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_version(token, id, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Delete Version", readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
)
def delete_version(id: int) -> dict[str, Any]:
    """Delete a version.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().delete_version(token, id)


# ─── Membership Tools ─────────────────────────────────────────────────

@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="List Memberships", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_memberships(
    page_size: int = 20,
    offset: int = 1,
    project_id: int | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List memberships (paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        project_id: ID of the project.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    filters = None
    if project_id is not None:
        import json as _json
        filters = _json.dumps([{"project": {"operator": "=", "values": [str(project_id)]}}])
    data = get_client().list_memberships(token, 
        page_size=page_size, offset=offset, filters=filters,
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Create Membership", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def create_membership(
    project_id: int,
    principal_id: int,
    role_ids: list[int],
) -> dict[str, Any]:
    """Create a membership.

    Args:
        project_id: ID of the project.
        principal_id: ID of the user or group.
        role_ids: List of role IDs.
    """
    token = get_user_token()
    data = MembershipCreate(project_id=project_id, principal_id=principal_id, role_ids=role_ids)
    return get_client().create_membership(token, _build_membership_payload(data), ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Get Membership By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_membership_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single membership by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_membership_by_id(token, id, include_all_fields=include_all_fields)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Update Membership", readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def update_membership(
    id: int,
    project_id: int | None = None,
    principal_id: int | None = None,
    role_ids: list[int] | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a membership.

    Args:
        id: ID of the resource.
        project_id: ID of the project.
        principal_id: ID of the user or group.
        role_ids: List of role IDs.
        lock_version: Lock version for optimistic locking.
    """
    token = get_user_token()
    links: dict[str, Any] = {}
    if project_id is not None:
        links["project"] = {"href": f"/api/v3/projects/{project_id}"}
    if principal_id is not None:
        links["principal"] = {"href": f"/api/v3/users/{principal_id}"}
    if role_ids is not None:
        links["roles"] = [{"href": f"/api/v3/roles/{rid}"} for rid in role_ids]
    payload: dict[str, Any] = {"_links": links}
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_membership(token, id, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Delete Membership", readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
)
def delete_membership(id: int) -> dict[str, Any]:
    """Delete a membership.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().delete_membership(token, id)


# ─── User Tools ───────────────────────────────────────────────────────

@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="List Users", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_users(
    page_size: int = 20,
    offset: int = 1,
    filters: FilterExpression | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List users (paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        filters: FilterExpression with conditions (field, operator, values).
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    data = get_client().list_users(token, 
        page_size=page_size, offset=offset, filters=_build_filter_string(filters),
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="Get User By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_user_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single user by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_user_by_id(token, id, include_all_fields=include_all_fields)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Create User", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def create_user(
    login: str,
    first_name: str,
    last_name: str,
    email: str,
    password: str,
    language: str = "en",
    admin: bool = False,
) -> dict[str, Any]:
    """Create a user.

    Args:
        login: Login username.
        first_name: First name.
        last_name: Last name.
        email: Email address.
        password: Password.
        language: Language code (Default: en).
        admin: true or false.
    """
    token = get_user_token()
    return get_client().create_user(token, {
        "login": login, "firstName": first_name, "lastName": last_name,
        "email": email, "password": password, "language": language, "admin": admin,
    }, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Update User", readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def update_user(
    id: int,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
    language: str | None = None,
    admin: bool | None = None,
) -> dict[str, Any]:
    """Update a user.

    Args:
        id: ID of the resource.
        first_name: First name.
        last_name: Last name.
        email: Email address.
        language: Language code.
        admin: true or false.
    """
    token = get_user_token()
    payload: dict[str, Any] = {}
    if first_name is not None:
        payload["firstName"] = first_name
    if last_name is not None:
        payload["lastName"] = last_name
    if email is not None:
        payload["email"] = email
    if language is not None:
        payload["language"] = language
    if admin is not None:
        payload["admin"] = admin
    return get_client().update_user(token, id, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Delete User", readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
)
def delete_user(id: int) -> dict[str, Any]:
    """Delete a user.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().delete_user(token, id)


# ─── Group Tools ──────────────────────────────────────────────────────

@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="List Groups", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_groups(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List groups (paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    data = get_client().list_groups(token, 
        page_size=page_size, offset=offset, include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Get Group By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_group_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single group by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_group_by_id(token, id, include_all_fields=include_all_fields)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Create Group", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def create_group(
    name: str,
    member_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Create a group.

    Args:
        name: Name.
        member_ids: List of member user IDs.
    """
    token = get_user_token()
    payload: dict[str, Any] = {"name": name}
    if member_ids:
        payload["_links"] = {
            "members": [{"href": f"/api/v3/users/{uid}"} for uid in member_ids]
        }
    return get_client().create_group(token, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Update Group", readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def update_group(
    id: int,
    name: str | None = None,
    member_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Update a group.

    Args:
        id: ID of the resource.
        name: Name.
        member_ids: List of member user IDs.
    """
    token = get_user_token()
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if member_ids is not None:
        payload["_links"] = {
            "members": [{"href": f"/api/v3/users/{uid}"} for uid in member_ids]
        }
    return get_client().update_group(token, id, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Delete Group", readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
)
def delete_group(id: int) -> dict[str, Any]:
    """Delete a group.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().delete_group(token, id)


# ─── Status Tools ─────────────────────────────────────────────────────

@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="List Statuses", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_statuses(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List statuses (paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    data = get_client().list_statuses(token, 
        page_size=page_size, offset=offset, include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="Get Status By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_status_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single status by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_status_by_id(token, id, include_all_fields=include_all_fields)


# ─── Type Tools ───────────────────────────────────────────────────────

@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="List Types", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_types(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List types (paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    data = get_client().list_types(token, 
        page_size=page_size, offset=offset, include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="Get Type By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_type_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single type by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_type_by_id(token, id, include_all_fields=include_all_fields)


# ─── Priority Tools ───────────────────────────────────────────────────

@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="List Priorities", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_priorities(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List priorities (paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    data = get_client().list_priorities(token, 
        page_size=page_size, offset=offset, include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="Get Priority By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_priority_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single priority by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_priority_by_id(token, id, include_all_fields=include_all_fields)


# ─── Role Tools ───────────────────────────────────────────────────────

@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="List Roles", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_roles(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List roles (paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    data = get_client().list_roles(token, 
        page_size=page_size, offset=offset, include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="Get Role By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_role_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single role by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_role_by_id(token, id, include_all_fields=include_all_fields)


# ─── Principal Tools ──────────────────────────────────────────────────

@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="List Principals", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_principals(
    page_size: int = 20,
    offset: int = 1,
    filters: FilterExpression | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List principals (users and groups, paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        filters: FilterExpression with conditions (field, operator, values).
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    data = get_client().list_principals(token, 
        page_size=page_size, offset=offset, filters=_build_filter_string(filters),
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Get Principal By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_principal_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single principal by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_principal_by_id(token, id, include_all_fields=include_all_fields)


# ─── Category Tools ───────────────────────────────────────────────────

@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Get Category By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_category_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single category by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_category_by_id(token, id, include_all_fields=include_all_fields)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="List Project Categories", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_project_categories(
    project_id: int,
    page_size: int = 20,
    offset: int = 1,
) -> dict[str, Any]:
    """List categories for a project.

    Args:
        project_id: ID of the project.
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
    """
    token = get_user_token()
    data = get_client().list_project_categories(token, project_id, page_size, offset)
    return {"items": json_to_toon(data)}
# ─── Wiki Page Tools ──────────────────────────────────────────────────

@mcp.tool(
    tags={"advanced", "openproject"}, annotations=ToolAnnotations(title="Get Wiki Page By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_wiki_page_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single wiki page by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_wiki_page_by_id(token, id, include_all_fields=include_all_fields)


# ─── Budget Tools ─────────────────────────────────────────────────────

@mcp.tool(
    tags={"advanced", "openproject"}, annotations=ToolAnnotations(title="Get Budget By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_budget_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single budget by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_budget_by_id(token, id, include_all_fields=include_all_fields)


@mcp.tool(
    tags={"advanced", "openproject"}, annotations=ToolAnnotations(title="List Project Budgets", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_project_budgets(
    project_id: int,
    page_size: int = 20,
    offset: int = 1,
) -> dict[str, Any]:
    """List budgets for a project.

    Args:
        project_id: ID of the project.
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
    """
    token = get_user_token()
    data = get_client().list_project_budgets(token, project_id, page_size, offset)
    return {"items": json_to_toon(data)}
@mcp.tool(
    tags={"advanced", "openproject"}, annotations=ToolAnnotations(title="Get Cost Type By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_cost_type_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single cost type by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_cost_type_by_id(token, id, include_all_fields=include_all_fields)


# ─── Notification Tools ───────────────────────────────────────────────

@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="List Notifications", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_notifications(
    page_size: int = 20,
    offset: int = 1,
    filters: FilterExpression | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List notifications (paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        filters: FilterExpression with conditions (field, operator, values).
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    data = get_client().list_notifications(token, 
        page_size=page_size, offset=offset, filters=_build_filter_string(filters),
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Get Notification By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_notification_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single notification by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_notification_by_id(token, id, include_all_fields=include_all_fields)


# ─── Days / Calendar Tools ────────────────────────────────────────────

@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="List Days", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_days(
    page_size: int = 20,
    offset: int = 1,
    working: bool | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List calendar days with working/non-working status.

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        working: true or false (filter by working day status).
        date_from: Date in YYYY-MM-DD format (2026-12-31).
        date_to: Date in YYYY-MM-DD format (2026-12-31).
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    import json as _json
    filters: list[dict[str, Any]] = []
    if working is not None:
        filters.append({"working": {"operator": "=", "values": ["t" if working else "f"]}})
    if date_from is not None and date_to is not None:
        filters.append({"date": {"operator": "<>d", "values": [date_from, date_to]}})
    filter_str = _json.dumps(filters) if filters else None
    data = get_client().list_days(token, 
        page_size=page_size, offset=offset, filters=filter_str,
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="List Non Working Days", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_non_working_days(
    page_size: int = 20,
    offset: int = 1,
    date_from: str | None = None,
    date_to: str | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List non-working days (holidays).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        date_from: Date in YYYY-MM-DD format (2026-12-31).
        date_to: Date in YYYY-MM-DD format (2026-12-31).
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    import json as _json
    filters: list[dict[str, Any]] = []
    if date_from is not None and date_to is not None:
        filters.append({"date": {"operator": "<>d", "values": [date_from, date_to]}})
    filter_str = _json.dumps(filters) if filters else None
    data = get_client().list_non_working_days(token, 
        page_size=page_size, offset=offset, filters=filter_str,
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Get Non Working Day By Date", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_non_working_day_by_date(date: str, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single non-working day by date.

    Args:
        date: Date in YYYY-MM-DD format (2026-12-31).
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    return get_client().get_non_working_day_by_date(token, date, include_all_fields=include_all_fields)


@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="List Week Days", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_week_days(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List configured week days (Mon-Sun with working flag).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    data = get_client().list_week_days(token, 
        page_size=page_size, offset=offset, include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"basic", "openproject"}, annotations=ToolAnnotations(title="Get Week Day By Number", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_week_day_by_number(day: str, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single week day by name.

    Args:
        day: Day of the week (Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, or Sunday).
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    return get_client().get_week_day_by_number(token, _DAY_NAMES[day.lower()], include_all_fields=include_all_fields)


# ─── Attachment Tools (metadata only) ────────────────────────────────

@mcp.tool(
    tags={"advanced", "openproject"}, annotations=ToolAnnotations(title="Get Attachment By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_attachment_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get attachment metadata by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_attachment_by_id(token, id, include_all_fields=include_all_fields)


# ─── Document Tools ───────────────────────────────────────────────────

@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="List Documents", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_documents(
    page_size: int = 20,
    offset: int = 1,
    project_id: int | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List documents (paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        project_id: ID of the project.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    import json as _json
    filters = None
    if project_id is not None:
        filters = _json.dumps([{"project": {"operator": "=", "values": [str(project_id)]}}])
    data = get_client().list_documents(token, 
        page_size=page_size, offset=offset, filters=filters,
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Get Document By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_document_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single document by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_document_by_id(token, id, include_all_fields=include_all_fields)


@mcp.tool(
    tags={"advanced", "openproject"}, annotations=ToolAnnotations(title="Update Document", readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def update_document(
    id: int,
    title: str | None = None,
    description: str | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a document.

    Args:
        id: ID of the resource.
        title: Title.
        description: Description text in markdown format.
        lock_version: Lock version for optimistic locking.
    """
    token = get_user_token()
    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if description is not None:
        payload["description"] = {"format": "markdown", "raw": description}
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_document(token, id, payload, ALLOW_ALL_AGGREGATE)


# ─── Emoji Reaction Tools ─────────────────────────────────────────────

@mcp.tool(
    tags={"advanced", "openproject"}, annotations=ToolAnnotations(title="List Emoji Reactions", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_emoji_reactions(activity_id: int) -> dict[str, Any]:
    """List emoji reactions on an activity.

    Args:
        activity_id: ID of the activity.
    """
    token = get_user_token()
    data = get_client().list_emoji_reactions(token, activity_id)
    return {"items": json_to_toon(data)}
@mcp.tool(
    tags={"advanced", "openproject"}, annotations=ToolAnnotations(title="Toggle Emoji Reaction", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def toggle_emoji_reaction(activity_id: int, reaction: str) -> dict[str, Any]:
    """Toggle an emoji reaction on an activity (add or remove).

    Args:
        activity_id: ID of the activity.
        reaction: Emoji reaction string.
    """
    token = get_user_token()
    return get_client().toggle_emoji_reaction(token, activity_id, reaction)


# ─── Wiki Page Link Tools ─────────────────────────────────────────────

# (wiki page link tools removed — no backend endpoint)


# ─── Reminder Tools ───────────────────────────────────────────────────

@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Create Reminder", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def create_reminder(
    work_package_id: int,
    remind_at: str,
    note: str = "",
) -> dict[str, Any]:
    """Create a reminder on a work package.

    Args:
        work_package_id: ID of the work package.
        remind_at: ISO 8601 format (2026-06-22T15:00:00-04:00).
        note: Note text.
    """
    token = get_user_token()
    payload: dict[str, Any] = {"remindAt": remind_at}
    if note:
        payload["note"] = note
    return get_client().create_reminder(token, work_package_id, payload)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="List Reminders", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_reminders(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List reminders (paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    data = get_client().list_reminders(token, 
        page_size=page_size, offset=offset, include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Update Reminder", readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def update_reminder(
    id: int,
    work_package_id: int | None = None,
    minutes_before: int | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Update a reminder.

    Args:
        id: ID of the resource.
        work_package_id: ID of the work package.
        minutes_before: Minutes before the event to trigger the reminder.
        note: Note text.
    """
    token = get_user_token()
    payload: dict[str, Any] = {}
    if work_package_id is not None:
        payload["_links"] = {"workPackage": {"href": f"/api/v3/work_packages/{work_package_id}"}}
    if minutes_before is not None:
        payload["minutesBefore"] = minutes_before
    if note is not None:
        payload["notes"] = note
    return get_client().update_reminder(token, id, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Delete Reminder", readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
)
def delete_reminder(id: int) -> dict[str, Any]:
    """Delete a reminder.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().delete_reminder(token, id)


# ─── Meeting Tools ────────────────────────────────────────────────────

@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="List Meetings", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_meetings(
    page_size: int = 20,
    offset: int = 1,
    project_id: int | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List meetings (paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        project_id: ID of the project.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    import json as _json
    filters = None
    if project_id is not None:
        filters = _json.dumps([{"project": {"operator": "=", "values": [str(project_id)]}}])
    data = get_client().list_meetings(token, 
        page_size=page_size, offset=offset, filters=filters,
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Create Meeting", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def create_meeting(
    title: str,
    project_id: int,
    start_time: str,
    end_time: str,
    location: str = "",
    notify: bool = True,
) -> dict[str, Any]:
    """Create a meeting.

    Args:
        title: Title.
        project_id: ID of the project.
        start_time: ISO 8601 format (2026-06-22T15:00:00-04:00).
        end_time: ISO 8601 format (2026-06-22T15:00:00-04:00).
        location: Location or video call link.
        notify: true or false (Default: true).
    """
    token = get_user_token()
    return get_client().create_meeting(token, {
        "title": title,
        "_links": {"project": {"href": f"/api/v3/projects/{project_id}"}},
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
        "notify": notify,
    }, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Get Meeting By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_meeting_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single meeting by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_meeting_by_id(token, id, include_all_fields=include_all_fields)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Update Meeting", readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def update_meeting(
    id: int,
    title: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    location: str | None = None,
    notify: bool | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a meeting.

    Args:
        id: ID of the resource.
        title: Title.
        start_time: ISO 8601 format (2026-06-22T15:00:00-04:00).
        end_time: ISO 8601 format (2026-06-22T15:00:00-04:00).
        location: Location or video call link.
        notify: true or false.
        lock_version: Lock version for optimistic locking.
    """
    token = get_user_token()
    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if start_time is not None:
        payload["startTime"] = start_time
    if end_time is not None:
        payload["endTime"] = end_time
    if location is not None:
        payload["location"] = location
    if notify is not None:
        payload["notify"] = notify
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_meeting(token, id, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Delete Meeting", readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
)
def delete_meeting(id: int) -> dict[str, Any]:
    """Delete a meeting.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().delete_meeting(token, id)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="List Meeting Agenda Items", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_meeting_agenda_items(meeting_id: int) -> dict[str, Any]:
    """List agenda items for a meeting.

    Args:
        meeting_id: ID of the meeting.
    """
    token = get_user_token()
    data = get_client().list_meeting_agenda_items(token, meeting_id)
    return {"items": json_to_toon(data)}
@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="List Meeting Sections", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_meeting_sections(meeting_id: int) -> dict[str, Any]:
    """List sections for a meeting.

    Args:
        meeting_id: ID of the meeting.
    """
    token = get_user_token()
    data = get_client().list_meeting_sections(token, meeting_id)
    return {"items": json_to_toon(data)}
# ─── Meeting Agenda Item Tools ────────────────────────────────────────

@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Create Meeting Agenda Item", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def create_meeting_agenda_item(
    meeting_id: int,
    item_type: str = "simple",
    title: str | None = None,
    duration_in_minutes: int | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Create a meeting agenda item.

    Args:
        meeting_id: ID of the meeting.
        item_type: simple or work_package (Default: simple).
        title: Title.
        duration_in_minutes: Duration in minutes.
        notes: Notes text in markdown format.
    """
    token = get_user_token()
    payload: dict[str, Any] = {
        "itemType": item_type,
        "_links": {"meeting": {"href": f"/api/v3/meetings/{meeting_id}"}},
    }
    if title is not None:
        payload["title"] = title
    if duration_in_minutes is not None:
        payload["durationInMinutes"] = duration_in_minutes
    if notes:
        payload["notes"] = {"format": "markdown", "raw": notes}
    return get_client().create_meeting_agenda_item(token, payload)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Get Meeting Agenda Item By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_meeting_agenda_item_by_id(meeting_id: int, id: int) -> dict[str, Any]:
    """Get a single meeting agenda item by ID.

    Args:
        meeting_id: ID of the meeting.
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_meeting_agenda_item_by_id(token, meeting_id, id)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Update Meeting Agenda Item", readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def update_meeting_agenda_item(
    id: int,
    title: str | None = None,
    duration_in_minutes: int | None = None,
    notes: str | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a meeting agenda item.

    Args:
        id: ID of the resource.
        title: Title.
        duration_in_minutes: Duration in minutes.
        notes: Notes text in markdown format.
        lock_version: Lock version for optimistic locking.
    """
    token = get_user_token()
    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if duration_in_minutes is not None:
        payload["durationInMinutes"] = duration_in_minutes
    if notes is not None:
        payload["notes"] = {"format": "markdown", "raw": notes}
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_meeting_agenda_item(token, id, payload)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Delete Meeting Agenda Item", readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
)
def delete_meeting_agenda_item(id: int) -> dict[str, Any]:
    """Delete a meeting agenda item.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().delete_meeting_agenda_item(token, id)


# ─── Meeting Section Tools ────────────────────────────────────────────

@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Create Meeting Section", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def create_meeting_section(
    meeting_id: int,
    title: str,
    position: int = 0,
) -> dict[str, Any]:
    """Create a meeting section.

    Args:
        meeting_id: ID of the meeting.
        title: Title.
        position: Position index.
    """
    token = get_user_token()
    return get_client().create_meeting_section(token, {
        "title": title,
        "position": position,
        "_links": {"meeting": {"href": f"/api/v3/meetings/{meeting_id}"}},
    })


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Get Meeting Section By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_meeting_section_by_id(meeting_id: int, id: int) -> dict[str, Any]:
    """Get a single meeting section by ID.

    Args:
        meeting_id: ID of the meeting.
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_meeting_section_by_id(token, meeting_id, id)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Update Meeting Section", readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def update_meeting_section(
    id: int,
    title: str | None = None,
    position: int | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a meeting section.

    Args:
        id: ID of the resource.
        title: Title.
        position: Position index.
        lock_version: Lock version for optimistic locking.
    """
    token = get_user_token()
    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if position is not None:
        payload["position"] = position
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_meeting_section(token, id, payload)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Delete Meeting Section", readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
)
def delete_meeting_section(id: int) -> dict[str, Any]:
    """Delete a meeting section.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().delete_meeting_section(token, id)


# ─── Recurring Meeting Tools ──────────────────────────────────────────

@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="List Recurring Meetings", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_recurring_meetings(
    page_size: int = 20,
    offset: int = 1,
    project_id: int | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List recurring meetings (paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        project_id: ID of the project.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    import json as _json
    filters = None
    if project_id is not None:
        filters = _json.dumps([{"project": {"operator": "=", "values": [str(project_id)]}}])
    data = get_client().list_recurring_meetings(token, 
        page_size=page_size, offset=offset, filters=filters,
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Create Recurring Meeting", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def create_recurring_meeting(
    project_id: int,
    title: str,
    frequency: str,
    start_time: str,
    end_time: str,
    days: list[str] | None = None,
    interval_value: int = 1,
    count_limit: int | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Create a recurring meeting.

    Args:
        project_id: ID of the project.
        title: Title.
        frequency: daily, working_days, weekly, monthly_day_of_month, or monthly_nth_weekday.
        start_time: ISO 8601 format (2026-06-22T15:00:00-04:00).
        end_time: ISO 8601 format (2026-06-22T15:00:00-04:00).
        days: Days of the week (Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, or Sunday).
        interval_value: Every Nth occurrence (Default: 1).
        count_limit: Maximum number of occurrences.
        end_date: Date in YYYY-MM-DD format (2026-12-31).
    """
    token = get_user_token()
    payload: dict[str, Any] = {
        "title": title,
        "frequency": frequency,
        "_links": {"project": {"href": f"/api/v3/projects/{project_id}"}},
        "start_time": start_time,
        "end_time": end_time,
        "intervalValue": interval_value,
    }
    if days is not None:
        payload["days"] = [_DAY_NAMES[d.lower()] for d in days]
    if count_limit is not None:
        payload["countLimit"] = count_limit
    if end_date is not None:
        payload["endDate"] = end_date
    return get_client().create_recurring_meeting(token, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Get Recurring Meeting By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_recurring_meeting_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single recurring meeting by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_recurring_meeting_by_id(token, id, include_all_fields=include_all_fields)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Update Recurring Meeting", readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def update_recurring_meeting(
    id: int,
    title: str | None = None,
    frequency: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    interval_value: int | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a recurring meeting.

    Args:
        id: ID of the resource.
        title: Title.
        frequency: daily, working_days, weekly, monthly_day_of_month, or monthly_nth_weekday.
        start_time: ISO 8601 format (2026-06-22T15:00:00-04:00).
        end_time: ISO 8601 format (2026-06-22T15:00:00-04:00).
        interval_value: Interval count.
        lock_version: Lock version for optimistic locking.
    """
    token = get_user_token()
    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if frequency is not None:
        payload["frequency"] = frequency
    if start_time is not None:
        payload["startTime"] = start_time
    if end_time is not None:
        payload["endTime"] = end_time
    if interval_value is not None:
        payload["intervalValue"] = interval_value
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_recurring_meeting(token, id, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Delete Recurring Meeting", readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
)
def delete_recurring_meeting(id: int) -> dict[str, Any]:
    """Delete a recurring meeting.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().delete_recurring_meeting(token, id)


# ─── Time Entry Tools ─────────────────────────────────────────────────

@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="List Time Entries", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_time_entries(
    page_size: int = 20,
    offset: int = 1,
    project_id: int | None = None,
    work_package_id: int | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List time entries (paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        project_id: ID of the project.
        work_package_id: ID of the work package.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    import json as _json
    filters: list[dict[str, Any]] = []
    if project_id is not None:
        filters.append({"project": {"operator": "=", "values": [str(project_id)]}})
    if work_package_id is not None:
        filters.append({"workPackage": {"operator": "=", "values": [str(work_package_id)]}})
    filter_str = _json.dumps(filters) if filters else None
    data = get_client().list_time_entries(token, 
        page_size=page_size, offset=offset, filters=filter_str,
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Create Time Entry", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def create_time_entry(
    project_id: int,
    hours: str,
    work_package_id: int | None = None,
    activity_id: int | None = None,
    spent_on: str | None = None,
    comment: str = "",
) -> dict[str, Any]:
    """Create a time entry.

    Args:
        project_id: ID of the project.
        hours: Time spent in ISO 8601 duration format (e.g. PT2H30M).
        work_package_id: ID of the work package.
        activity_id: ID of the activity.
        spent_on: Date in YYYY-MM-DD format (2026-12-31).
        comment: Comment text.
    """
    token = get_user_token()
    links: dict[str, Any] = {"project": {"href": f"/api/v3/projects/{project_id}"}}
    if work_package_id is not None:
        links["entity"] = {"href": f"/api/v3/work_packages/{work_package_id}"}
    if activity_id is not None:
        links["activity"] = {"href": f"/api/v3/time_entries/activities/{activity_id}"}
    payload: dict[str, Any] = {
        "hours": hours,
        "_links": links,
    }
    if spent_on is not None:
        payload["spentOn"] = spent_on
    if comment:
        payload["comment"] = {"format": "markdown", "raw": comment}
    return get_client().create_time_entry(token, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Get Time Entry By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_time_entry_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single time entry by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_time_entry_by_id(token, id, include_all_fields=include_all_fields)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Update Time Entry", readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def update_time_entry(
    id: int,
    hours: str | None = None,
    spent_on: str | None = None,
    comment: str | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a time entry.

    Args:
        id: ID of the resource.
        hours: Time spent in ISO 8601 duration format (e.g. PT2H30M).
        spent_on: Date in YYYY-MM-DD format (2026-12-31).
        comment: Comment text.
        lock_version: Lock version for optimistic locking.
    """
    token = get_user_token()
    payload: dict[str, Any] = {}
    if hours is not None:
        payload["hours"] = hours
    if spent_on is not None:
        payload["spentOn"] = spent_on
    if comment is not None:
        payload["comment"] = {"format": "markdown", "raw": comment}
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_time_entry(token, id, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Delete Time Entry", readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
)
def delete_time_entry(id: int) -> dict[str, Any]:
    """Delete a time entry.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().delete_time_entry(token, id)


# ─── News Tools ───────────────────────────────────────────────────────

@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="List News", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_news(
    page_size: int = 20,
    offset: int = 1,
    project_id: int | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List news items (paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        project_id: ID of the project.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    import json as _json
    filters = None
    if project_id is not None:
        filters = _json.dumps([{"project": {"operator": "=", "values": [str(project_id)]}}])
    data = get_client().list_news(token, 
        page_size=page_size, offset=offset, filters=filters,
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Create News", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def create_news(
    project_id: int,
    title: str,
    summary: str = "",
    description: str = "",
) -> dict[str, Any]:
    """Create a news item.

    Args:
        project_id: ID of the project.
        title: Title.
        summary: Short summary.
        description: Description text in markdown format.
    """
    token = get_user_token()
    payload: dict[str, Any] = {
        "title": title,
        "_links": {"project": {"href": f"/api/v3/projects/{project_id}"}},
    }
    if summary:
        payload["summary"] = summary
    if description:
        payload["description"] = {"format": "markdown", "raw": description}
    return get_client().create_news(token, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Get News By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_news_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single news item by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_news_by_id(token, id, include_all_fields=include_all_fields)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Update News", readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def update_news(
    id: int,
    title: str | None = None,
    summary: str | None = None,
    description: str | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a news item.

    Args:
        id: ID of the resource.
        title: Title.
        summary: Short summary.
        description: Description text in markdown format.
        lock_version: Lock version for optimistic locking.
    """
    token = get_user_token()
    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if summary is not None:
        payload["summary"] = summary
    if description is not None:
        payload["description"] = {"format": "markdown", "raw": description}
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_news(token, id, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"primary", "openproject"}, annotations=ToolAnnotations(title="Delete News", readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
)
def delete_news(id: int) -> dict[str, Any]:
    """Delete a news item.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().delete_news(token, id)


# ─── Grid Tools ───────────────────────────────────────────────────────

@mcp.tool(
    tags={"advanced", "openproject"}, annotations=ToolAnnotations(title="List Grids", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def list_grids(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List grids (paginated).

    Args:
        page_size: Number of items per page (Default: 20).
        offset: Page offset for pagination.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    token = get_user_token()
    data = get_client().list_grids(token, 
        page_size=page_size, offset=offset, include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False
    )
    return {"items": json_to_toon(data)}


@mcp.tool(
    tags={"advanced", "openproject"}, annotations=ToolAnnotations(title="Create Grid", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def create_grid(
    page: str,
    row_count: int = 3,
    column_count: int = 2,
    scope_href: str | None = None,
) -> dict[str, Any]:
    """Create a grid.

    Args:
        page: Page identifier (e.g. overview, project-overview, my_page).
        row_count: Number of rows (Default: 3).
        column_count: Number of columns (Default: 2).
        scope_href: Scope URL for the grid.
    """
    token = get_user_token()
    payload: dict[str, Any] = {
        "name": page,
        "rowCount": row_count,
        "columnCount": column_count,
        "options": {},
        "widgets": [],
    }
    if scope_href:
        payload["_links"] = {"scope": {"href": scope_href, "type": "text/html"}}
    return get_client().create_grid(token, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"advanced", "openproject"}, annotations=ToolAnnotations(title="Get Grid By Id", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_grid_by_id(id: int, include_all_fields: bool = False) -> dict[str, Any]:
    """Get a single grid by ID.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().get_grid_by_id(token, id, include_all_fields=include_all_fields)


@mcp.tool(
    tags={"advanced", "openproject"}, annotations=ToolAnnotations(title="Update Grid", readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def update_grid(
    id: int,
    page: str | None = None,
    row_count: int | None = None,
    widgets: list[GridWidget] | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a grid.

    Args:
        id: ID of the resource.
        page: Page identifier (e.g. overview, project-overview, my_page).
        row_count: Number of rows.
        widgets: List of grid widget configurations.
        lock_version: Lock version for optimistic locking.
    """
    token = get_user_token()
    payload: dict[str, Any] = {}
    if page is not None:
        payload["page"] = page
    if row_count is not None:
        payload["rowCount"] = row_count
    if widgets is not None:
        payload["widgets"] = _build_widgets_payload(widgets)
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_grid(token, id, payload, ALLOW_ALL_AGGREGATE)


@mcp.tool(
    tags={"advanced", "openproject"}, annotations=ToolAnnotations(title="Delete Grid", readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
)
def delete_grid(id: int) -> dict[str, Any]:
    """Delete a grid.

    Args:
        id: ID of the resource.
    """
    token = get_user_token()
    return get_client().delete_grid(token, id)


# ─── Job Status ────────────────────────────────────────────────────────

@mcp.tool(
    tags={"advanced", "openproject"}, annotations=ToolAnnotations(title="Get Job Status", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def get_job_status(job_id: str) -> dict[str, Any]:
    """Get the status of an async job.

    Args:
        job_id: ID of the async job.
    """
    token = get_user_token()
    return get_client().get_job_status(token, job_id)


# ─── Health check ─────────────────────────────────────────────────────

@mcp.tool(
    tags={"advanced", "openproject"}, annotations=ToolAnnotations(title="Health Check", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def health_check() -> dict[str, str]:
    """Basic server health check."""
    token = get_user_token()
    return {"status": "ok"}


# ─── Main entry point ─────────────────────────────────────────────────

def main() -> None:
    import uvicorn
    port = MCP_SERVER_PORT
    if IS_STATEFUL:
        app = mcp.http_app()
    else:
        app = mcp.http_app(stateless_http=True)
    app = AuthMiddleware(app)
    print(f"Starting OpenProject MCP server on port {port} {'stateful' if IS_STATEFUL else 'stateless'}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
    token = get_user_token()