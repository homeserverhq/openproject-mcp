"""OpenProject MCP server entry point."""

from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP

from src.client import OpenProjectClient

API_KEY = os.environ.get("API_KEY", "")
MCP_SERVER_PORT = int(os.environ.get("MCP_SERVER_PORT", "6893"))

# Global client instance (per-request token override via context)
_client: OpenProjectClient | None = None


def get_client() -> OpenProjectClient:
    global _client
    if _client is None:
        _client = OpenProjectClient(API_KEY)
    return _client


# ─── FastMCP instance ─────────────────────────────────────────────────

mcp = FastMCP("OpenProject MCP Server")


# ─── Pydantic contract models ─────────────────────────────────────────

from pydantic import BaseModel


class WPCreate(BaseModel):
    subject: str
    project_id: int
    type_id: int
    description: str = ""
    status_id: int | None = None
    priority_id: int | None = None
    assignee_id: int | None = None
    responsible_id: int | None = None
    version_id: int | None = None
    parent_id: int | None = None
    start_date: str | None = None
    due_date: str | None = None
    estimated_time: str | None = None
    duration: str | None = None
    schedule_manually: bool = False
    ignore_non_working_days: bool = False
    category_id: int | None = None


class WPUpdate(BaseModel):
    subject: str | None = None
    description: str | None = None
    status_id: int | None = None
    priority_id: int | None = None
    assignee_id: int | None = None
    responsible_id: int | None = None
    version_id: int | None = None
    parent_id: int | None = None
    start_date: str | None = None
    due_date: str | None = None
    estimated_time: str | None = None
    duration: str | None = None
    schedule_manually: bool | None = None
    ignore_non_working_days: bool | None = None
    percentage_done: int | None = None
    lock_version: int | None = None


class ProjectCreate(BaseModel):
    name: str
    identifier: str
    description: str = ""
    public: bool = True
    active: bool = True
    status_id: str | None = None
    parent_id: int | None = None
    status_explanation: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    public: bool | None = None
    active: bool | None = None
    status_id: str | None = None
    parent_id: int | None = None
    status_explanation: str | None = None
    lock_version: int | None = None


class VersionCreate(BaseModel):
    name: str
    project_id: int
    description: str = ""
    status: str = "open"
    sharing: str = "none"
    start_date: str | None = None
    end_date: str | None = None


class VersionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    sharing: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    lock_version: int | None = None


class MembershipCreate(BaseModel):
    project_id: int
    principal_id: int
    role_ids: list[int]


class MembershipUpdate(BaseModel):
    project_id: int | None = None
    principal_id: int | None = None
    role_ids: list[int] | None = None
    lock_version: int | None = None


class MeetingCreate(BaseModel):
    title: str
    project_id: int
    start_time: str
    end_time: str
    location: str = ""
    notify: bool = True


class MeetingUpdate(BaseModel):
    title: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    location: str | None = None
    notify: bool | None = None
    lock_version: int | None = None


class TimeEntryCreate(BaseModel):
    project_id: int
    work_package_id: int | None = None
    user_id: int | None = None
    activity_id: int | None = None
    hours: str
    spent_on: str | None = None
    comment: str = ""


class TimeEntryUpdate(BaseModel):
    project_id: int | None = None
    work_package_id: int | None = None
    hours: str | None = None
    spent_on: str | None = None
    comment: str | None = None
    lock_version: int | None = None


class NewsCreate(BaseModel):
    project_id: int
    title: str
    summary: str = ""
    description: str = ""


class NewsUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    description: str | None = None
    lock_version: int | None = None


class GridCreate(BaseModel):
    page: str
    row_count: int = 5


class GridUpdate(BaseModel):
    page: str | None = None
    row_count: int | None = None
    widgets: list[dict[str, Any]] | None = None
    lock_version: int | None = None


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


# ─── Work Package Tools ───────────────────────────────────────────────

@mcp.tool()
def list_work_packages(
    page_size: int = 20,
    offset: int = 1,
    project_id: int | None = None,
    status_id: int | None = None,
    type_id: int | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List work packages (paginated). (required: none)"""
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
    return get_client().list_work_packages(
        page_size=page_size, offset=offset, filters=filter_str,
        include_all_fields=include_all_fields
    )


@mcp.tool()
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
    """Create a work package. (required: subject, project_id, type_id)"""
    data = WPCreate(
        subject=subject, project_id=project_id, type_id=type_id,
        description=description, status_id=status_id, priority_id=priority_id,
        assignee_id=assignee_id, responsible_id=responsible_id,
        version_id=version_id, parent_id=parent_id, start_date=start_date,
        due_date=due_date, estimated_time=estimated_time, duration=duration,
        schedule_manually=schedule_manually,
        ignore_non_working_days=ignore_non_working_days, category_id=category_id,
    )
    return get_client().create_work_package(_build_wp_payload(data))


@mcp.tool()
def get_work_package_by_id(id: int) -> dict[str, Any]:
    """Get a single work package by ID. (required: id)"""
    return get_client().get_work_package_by_id(id)


@mcp.tool()
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
    """Update a work package. (required: id)"""
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
    return get_client().update_work_package(id, payload)


@mcp.tool()
def delete_work_package(id: int) -> dict[str, Any]:
    """Delete a work package. (required: id)"""
    return get_client().delete_work_package(id)


@mcp.tool()
def get_work_package_activities(
    id: int,
    page_size: int = 20,
    offset: int = 1,
) -> dict[str, Any]:
    """List activities (comments/journal entries) on a work package. (required: id)"""
    return get_client().get_work_package_activities(id, page_size, offset)


@mcp.tool()
def add_work_package_comment(id: int, comment: str) -> dict[str, Any]:
    """Add a comment to a work package. (required: id, comment)"""
    return get_client().add_work_package_comment(id, comment)


@mcp.tool()
def get_work_package_relations(id: int) -> dict[str, Any]:
    """List relations for a work package. (required: id)"""
    return get_client().get_work_package_relations(id)


@mcp.tool()
def create_work_package_relation(
    id: int,
    target_id: int,
    relation_type: str = "relates",
) -> dict[str, Any]:
    """Create a relation from a work package to another. (required: id, target_id, relation_type)"""
    return get_client().create_work_package_relation(
        id,
        {"_links": {"to": {"href": f"/api/v3/work_packages/{target_id}"}}, "type": relation_type},
    )


@mcp.tool()
def get_work_package_watchers(id: int) -> dict[str, Any]:
    """List watchers of a work package. (required: id)"""
    return get_client().get_work_package_watchers(id)


@mcp.tool()
def add_work_package_watcher(id: int, user_id: int) -> dict[str, Any]:
    """Add a watcher to a work package. (required: id, user_id)"""
    return get_client().add_work_package_watcher(id, user_id)


@mcp.tool()
def remove_work_package_watcher(id: int, user_id: int) -> dict[str, Any]:
    """Remove a watcher from a work package. (required: id, user_id)"""
    return get_client().remove_work_package_watcher(id, user_id)


@mcp.tool()
def list_work_package_attachments(
    id: int,
    page_size: int = 20,
    offset: int = 1,
) -> dict[str, Any]:
    """List attachment metadata for a work package. (required: id)"""
    return get_client().list_work_package_attachments(id, page_size, offset)


# ─── Project Tools ────────────────────────────────────────────────────

@mcp.tool()
def list_projects(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List projects (paginated). (required: none)"""
    return get_client().list_projects(
        page_size=page_size, offset=offset, include_all_fields=include_all_fields
    )


@mcp.tool()
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
    """Create a project. (required: name, identifier)"""
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
    return get_client().create_project(payload)


@mcp.tool()
def get_project_by_id(id: int) -> dict[str, Any]:
    """Get a single project by ID. (required: id)"""
    return get_client().get_project_by_id(id)


@mcp.tool()
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
    """Update a project. (required: id)"""
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
    return get_client().update_project(id, payload)


@mcp.tool()
def delete_project(id: int) -> dict[str, Any]:
    """Delete a project. (required: id)"""
    return get_client().delete_project(id)


@mcp.tool()
def copy_project(
    id: int,
    name: str | None = None,
    identifier: str | None = None,
) -> dict[str, Any]:
    """Copy a project. (required: id)"""
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if identifier is not None:
        payload["identifier"] = identifier
    return get_client().copy_project(id, payload)


# ─── Version Tools ────────────────────────────────────────────────────

@mcp.tool()
def list_versions(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List versions (paginated). (required: none)"""
    return get_client().list_versions(
        page_size=page_size, offset=offset, include_all_fields=include_all_fields
    )


@mcp.tool()
def create_version(
    name: str,
    project_id: int,
    description: str = "",
    status: str = "open",
    sharing: str = "none",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Create a version. (required: name, project_id)"""
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
    return get_client().create_version(payload)


@mcp.tool()
def get_version_by_id(id: int) -> dict[str, Any]:
    """Get a single version by ID. (required: id)"""
    return get_client().get_version_by_id(id)


@mcp.tool()
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
    """Update a version. (required: id)"""
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
    return get_client().update_version(id, payload)


@mcp.tool()
def delete_version(id: int) -> dict[str, Any]:
    """Delete a version. (required: id)"""
    return get_client().delete_version(id)


# ─── Membership Tools ─────────────────────────────────────────────────

@mcp.tool()
def list_memberships(
    page_size: int = 20,
    offset: int = 1,
    project_id: int | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List memberships (paginated). (required: none)"""
    filters = None
    if project_id is not None:
        import json as _json
        filters = _json.dumps([{"project": {"operator": "=", "values": [str(project_id)]}}])
    return get_client().list_memberships(
        page_size=page_size, offset=offset, filters=filters,
        include_all_fields=include_all_fields
    )


@mcp.tool()
def create_membership(
    project_id: int,
    principal_id: int,
    role_ids: list[int],
) -> dict[str, Any]:
    """Create a membership. (required: project_id, principal_id, role_ids)"""
    data = MembershipCreate(project_id=project_id, principal_id=principal_id, role_ids=role_ids)
    return get_client().create_membership(_build_membership_payload(data))


@mcp.tool()
def get_membership_by_id(id: int) -> dict[str, Any]:
    """Get a single membership by ID. (required: id)"""
    return get_client().get_membership_by_id(id)


@mcp.tool()
def update_membership(
    id: int,
    project_id: int | None = None,
    principal_id: int | None = None,
    role_ids: list[int] | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a membership. (required: id)"""
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
    return get_client().update_membership(id, payload)


@mcp.tool()
def delete_membership(id: int) -> dict[str, Any]:
    """Delete a membership. (required: id)"""
    return get_client().delete_membership(id)


# ─── User Tools ───────────────────────────────────────────────────────

@mcp.tool()
def list_users(
    page_size: int = 20,
    offset: int = 1,
    filters: str | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List users (paginated). (required: none)"""
    return get_client().list_users(
        page_size=page_size, offset=offset, filters=filters,
        include_all_fields=include_all_fields
    )


@mcp.tool()
def get_user_by_id(id: int) -> dict[str, Any]:
    """Get a single user by ID. (required: id)"""
    return get_client().get_user_by_id(id)


@mcp.tool()
def create_user(
    login: str,
    first_name: str,
    last_name: str,
    email: str,
    password: str,
    language: str = "en",
    admin: bool = False,
) -> dict[str, Any]:
    """Create a user. (required: login, first_name, last_name, email, password)"""
    return get_client().create_user({
        "login": login, "firstName": first_name, "lastName": last_name,
        "email": email, "password": password, "language": language, "admin": admin,
    })


@mcp.tool()
def update_user(
    id: int,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
    language: str | None = None,
    admin: bool | None = None,
) -> dict[str, Any]:
    """Update a user. (required: id)"""
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
    return get_client().update_user(id, payload)


@mcp.tool()
def delete_user(id: int) -> dict[str, Any]:
    """Delete a user. (required: id)"""
    return get_client().delete_user(id)


# ─── Group Tools ──────────────────────────────────────────────────────

@mcp.tool()
def list_groups(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List groups (paginated). (required: none)"""
    return get_client().list_groups(
        page_size=page_size, offset=offset, include_all_fields=include_all_fields
    )


@mcp.tool()
def get_group_by_id(id: int) -> dict[str, Any]:
    """Get a single group by ID. (required: id)"""
    return get_client().get_group_by_id(id)


@mcp.tool()
def create_group(
    name: str,
    member_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Create a group. (required: name)"""
    payload: dict[str, Any] = {"name": name}
    if member_ids:
        payload["_links"] = {
            "members": [{"href": f"/api/v3/users/{uid}"} for uid in member_ids]
        }
    return get_client().create_group(payload)


@mcp.tool()
def update_group(
    id: int,
    name: str | None = None,
    member_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Update a group. (required: id)"""
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if member_ids is not None:
        payload["_links"] = {
            "members": [{"href": f"/api/v3/users/{uid}"} for uid in member_ids]
        }
    return get_client().update_group(id, payload)


@mcp.tool()
def delete_group(id: int) -> dict[str, Any]:
    """Delete a group. (required: id)"""
    return get_client().delete_group(id)


# ─── Status Tools ─────────────────────────────────────────────────────

@mcp.tool()
def list_statuses(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List statuses (paginated). (required: none)"""
    return get_client().list_statuses(
        page_size=page_size, offset=offset, include_all_fields=include_all_fields
    )


@mcp.tool()
def get_status_by_id(id: int) -> dict[str, Any]:
    """Get a single status by ID. (required: id)"""
    return get_client().get_status_by_id(id)


# ─── Type Tools ───────────────────────────────────────────────────────

@mcp.tool()
def list_types(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List types (paginated). (required: none)"""
    return get_client().list_types(
        page_size=page_size, offset=offset, include_all_fields=include_all_fields
    )


@mcp.tool()
def get_type_by_id(id: int) -> dict[str, Any]:
    """Get a single type by ID. (required: id)"""
    return get_client().get_type_by_id(id)


# ─── Priority Tools ───────────────────────────────────────────────────

@mcp.tool()
def list_priorities(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List priorities (paginated). (required: none)"""
    return get_client().list_priorities(
        page_size=page_size, offset=offset, include_all_fields=include_all_fields
    )


@mcp.tool()
def get_priority_by_id(id: int) -> dict[str, Any]:
    """Get a single priority by ID. (required: id)"""
    return get_client().get_priority_by_id(id)


# ─── Role Tools ───────────────────────────────────────────────────────

@mcp.tool()
def list_roles(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List roles (paginated). (required: none)"""
    return get_client().list_roles(
        page_size=page_size, offset=offset, include_all_fields=include_all_fields
    )


@mcp.tool()
def get_role_by_id(id: int) -> dict[str, Any]:
    """Get a single role by ID. (required: id)"""
    return get_client().get_role_by_id(id)


# ─── Principal Tools ──────────────────────────────────────────────────

@mcp.tool()
def list_principals(
    page_size: int = 20,
    offset: int = 1,
    filters: str | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List principals (users and groups, paginated). (required: none)"""
    return get_client().list_principals(
        page_size=page_size, offset=offset, filters=filters,
        include_all_fields=include_all_fields
    )


@mcp.tool()
def get_principal_by_id(id: int) -> dict[str, Any]:
    """Get a single principal by ID. (required: id)"""
    return get_client().get_principal_by_id(id)


# ─── Category Tools ───────────────────────────────────────────────────

@mcp.tool()
def get_category_by_id(id: int) -> dict[str, Any]:
    """Get a single category by ID. (required: id)"""
    return get_client().get_category_by_id(id)


@mcp.tool()
def list_project_categories(
    project_id: int,
    page_size: int = 20,
    offset: int = 1,
) -> dict[str, Any]:
    """List categories for a project. (required: project_id)"""
    return get_client().list_project_categories(project_id, page_size, offset)


# ─── Wiki Page Tools ──────────────────────────────────────────────────

@mcp.tool()
def get_wiki_page_by_id(id: int) -> dict[str, Any]:
    """Get a single wiki page by ID. (required: id)"""
    return get_client().get_wiki_page_by_id(id)


# ─── Budget Tools ─────────────────────────────────────────────────────

@mcp.tool()
def get_budget_by_id(id: int) -> dict[str, Any]:
    """Get a single budget by ID. (required: id)"""
    return get_client().get_budget_by_id(id)


@mcp.tool()
def list_project_budgets(
    project_id: int,
    page_size: int = 20,
    offset: int = 1,
) -> dict[str, Any]:
    """List budgets for a project. (required: project_id)"""
    return get_client().list_project_budgets(project_id, page_size, offset)


@mcp.tool()
def get_cost_type_by_id(id: int) -> dict[str, Any]:
    """Get a single cost type by ID. (required: id)"""
    return get_client().get_cost_type_by_id(id)


# ─── Notification Tools ───────────────────────────────────────────────

@mcp.tool()
def list_notifications(
    page_size: int = 20,
    offset: int = 1,
    filters: str | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List notifications (paginated). (required: none)"""
    return get_client().list_notifications(
        page_size=page_size, offset=offset, filters=filters,
        include_all_fields=include_all_fields
    )


@mcp.tool()
def get_notification_by_id(id: int) -> dict[str, Any]:
    """Get a single notification by ID. (required: id)"""
    return get_client().get_notification_by_id(id)


# ─── Days / Calendar Tools ────────────────────────────────────────────

@mcp.tool()
def list_days(
    page_size: int = 20,
    offset: int = 1,
    working: bool | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List calendar days with working/non-working status. (required: none)"""
    import json as _json
    filters: list[dict[str, Any]] = []
    if working is not None:
        filters.append({"working": {"operator": "=", "values": ["t" if working else "f"]}})
    if date_from is not None and date_to is not None:
        filters.append({"date": {"operator": "<>d", "values": [date_from, date_to]}})
    filter_str = _json.dumps(filters) if filters else None
    return get_client().list_days(
        page_size=page_size, offset=offset, filters=filter_str,
        include_all_fields=include_all_fields
    )


@mcp.tool()
def list_non_working_days(
    page_size: int = 20,
    offset: int = 1,
    date_from: str | None = None,
    date_to: str | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List non-working days (holidays). (required: none)"""
    import json as _json
    filters: list[dict[str, Any]] = []
    if date_from is not None and date_to is not None:
        filters.append({"date": {"operator": "<>d", "values": [date_from, date_to]}})
    filter_str = _json.dumps(filters) if filters else None
    return get_client().list_non_working_days(
        page_size=page_size, offset=offset, filters=filter_str,
        include_all_fields=include_all_fields
    )


@mcp.tool()
def get_non_working_day_by_date(date: str) -> dict[str, Any]:
    """Get a single non-working day by date. (required: date, ISO 8601 format YYYY-MM-DD)"""
    return get_client().get_non_working_day_by_date(date)


@mcp.tool()
def list_week_days(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List configured week days (Mon-Sun with working flag). (required: none)"""
    return get_client().list_week_days(
        page_size=page_size, offset=offset, include_all_fields=include_all_fields
    )


@mcp.tool()
def get_week_day_by_number(day: int) -> dict[str, Any]:
    """Get a single week day by number (1=Monday, 7=Sunday). (required: day, 1-7)"""
    return get_client().get_week_day_by_number(day)


# ─── Attachment Tools (metadata only) ────────────────────────────────

@mcp.tool()
def get_attachment_by_id(id: int) -> dict[str, Any]:
    """Get attachment metadata by ID. (required: id)"""
    return get_client().get_attachment_by_id(id)


# ─── Document Tools ───────────────────────────────────────────────────

@mcp.tool()
def list_documents(
    page_size: int = 20,
    offset: int = 1,
    project_id: int | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List documents (paginated). (required: none)"""
    import json as _json
    filters = None
    if project_id is not None:
        filters = _json.dumps([{"project": {"operator": "=", "values": [str(project_id)]}}])
    return get_client().list_documents(
        page_size=page_size, offset=offset, filters=filters,
        include_all_fields=include_all_fields
    )


@mcp.tool()
def get_document_by_id(id: int) -> dict[str, Any]:
    """Get a single document by ID. (required: id)"""
    return get_client().get_document_by_id(id)


@mcp.tool()
def update_document(
    id: int,
    title: str | None = None,
    description: str | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a document. (required: id)"""
    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if description is not None:
        payload["description"] = {"format": "markdown", "raw": description}
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_document(id, payload)


# ─── Emoji Reaction Tools ─────────────────────────────────────────────

@mcp.tool()
def list_emoji_reactions(activity_id: int) -> dict[str, Any]:
    """List emoji reactions on an activity. (required: activity_id)"""
    return get_client().list_emoji_reactions(activity_id)


@mcp.tool()
def toggle_emoji_reaction(activity_id: int, reaction: str) -> dict[str, Any]:
    """Toggle an emoji reaction on an activity (add or remove). (required: activity_id, reaction)"""
    return get_client().toggle_emoji_reaction(activity_id, reaction)


# ─── Wiki Page Link Tools ─────────────────────────────────────────────

# (wiki page link tools removed — no backend endpoint)


# ─── Reminder Tools ───────────────────────────────────────────────────

@mcp.tool()
def create_reminder(
    work_package_id: int,
    remind_at: str,
    note: str = "",
) -> dict[str, Any]:
    """Create a reminder on a work package. (required: work_package_id, remind_at - ISO 8601 datetime, e.g. '2026-07-01T10:00:00Z')"""
    payload: dict[str, Any] = {"remindAt": remind_at}
    if note:
        payload["note"] = note
    return get_client().create_reminder(work_package_id, payload)


@mcp.tool()
def list_reminders(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List reminders (paginated). (required: none)"""
    return get_client().list_reminders(
        page_size=page_size, offset=offset, include_all_fields=include_all_fields
    )


@mcp.tool()
def update_reminder(
    id: int,
    work_package_id: int | None = None,
    minutes_before: int | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Update a reminder. (required: id)"""
    payload: dict[str, Any] = {}
    if work_package_id is not None:
        payload["_links"] = {"workPackage": {"href": f"/api/v3/work_packages/{work_package_id}"}}
    if minutes_before is not None:
        payload["minutesBefore"] = minutes_before
    if note is not None:
        payload["notes"] = note
    return get_client().update_reminder(id, payload)


@mcp.tool()
def delete_reminder(id: int) -> dict[str, Any]:
    """Delete a reminder. (required: id)"""
    return get_client().delete_reminder(id)


# ─── Meeting Tools ────────────────────────────────────────────────────

@mcp.tool()
def list_meetings(
    page_size: int = 20,
    offset: int = 1,
    project_id: int | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List meetings (paginated). (required: none)"""
    import json as _json
    filters = None
    if project_id is not None:
        filters = _json.dumps([{"project": {"operator": "=", "values": [str(project_id)]}}])
    return get_client().list_meetings(
        page_size=page_size, offset=offset, filters=filters,
        include_all_fields=include_all_fields
    )


@mcp.tool()
def create_meeting(
    title: str,
    project_id: int,
    start_time: str,
    end_time: str,
    location: str = "",
    notify: bool = True,
) -> dict[str, Any]:
    """Create a meeting. (required: title, project_id, start_time, end_time)"""
    return get_client().create_meeting({
        "title": title,
        "_links": {"project": {"href": f"/api/v3/projects/{project_id}"}},
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
        "notify": notify,
    })


@mcp.tool()
def get_meeting_by_id(id: int) -> dict[str, Any]:
    """Get a single meeting by ID. (required: id)"""
    return get_client().get_meeting_by_id(id)


@mcp.tool()
def update_meeting(
    id: int,
    title: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    location: str | None = None,
    notify: bool | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a meeting. (required: id)"""
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
    return get_client().update_meeting(id, payload)


@mcp.tool()
def delete_meeting(id: int) -> dict[str, Any]:
    """Delete a meeting. (required: id)"""
    return get_client().delete_meeting(id)


@mcp.tool()
def list_meeting_agenda_items(meeting_id: int) -> dict[str, Any]:
    """List agenda items for a meeting. (required: meeting_id)"""
    return get_client().list_meeting_agenda_items(meeting_id)


@mcp.tool()
def list_meeting_sections(meeting_id: int) -> dict[str, Any]:
    """List sections for a meeting. (required: meeting_id)"""
    return get_client().list_meeting_sections(meeting_id)


# ─── Meeting Agenda Item Tools ────────────────────────────────────────

@mcp.tool()
def create_meeting_agenda_item(
    meeting_id: int,
    item_type: str = "simple",
    title: str | None = None,
    duration_in_minutes: int | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Create a meeting agenda item. (required: meeting_id, item_type)"""
    payload: dict[str, Any] = {
        "itemType": item_type,
    }
    if title is not None:
        payload["title"] = title
    if duration_in_minutes is not None:
        payload["durationInMinutes"] = duration_in_minutes
    if notes:
        payload["notes"] = {"format": "markdown", "raw": notes}
    return get_client().create_meeting_agenda_item(meeting_id, payload)


@mcp.tool()
def get_meeting_agenda_item_by_id(meeting_id: int, id: int) -> dict[str, Any]:
    """Get a single meeting agenda item by ID. (required: meeting_id, id)"""
    return get_client().get_meeting_agenda_item_by_id(meeting_id, id)


@mcp.tool()
def update_meeting_agenda_item(
    meeting_id: int,
    id: int,
    title: str | None = None,
    duration_in_minutes: int | None = None,
    notes: str | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a meeting agenda item. (required: meeting_id, id)"""
    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if duration_in_minutes is not None:
        payload["durationInMinutes"] = duration_in_minutes
    if notes is not None:
        payload["notes"] = {"format": "markdown", "raw": notes}
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_meeting_agenda_item(meeting_id, id, payload)


@mcp.tool()
def delete_meeting_agenda_item(meeting_id: int, id: int) -> dict[str, Any]:
    """Delete a meeting agenda item. (required: meeting_id, id)"""
    return get_client().delete_meeting_agenda_item(meeting_id, id)


# ─── Meeting Outcome Tools ────────────────────────────────────────────

@mcp.tool()
def create_meeting_outcome(
    meeting_id: int,
    meeting_agenda_item_id: int,
    outcome_type: str = "simple",
    text: str = "",
) -> dict[str, Any]:
    """Create a meeting outcome. (required: meeting_id, meeting_agenda_item_id, outcome_type)"""
    return get_client().create_meeting_outcome(meeting_id, meeting_agenda_item_id, {
        "outcomeType": outcome_type,
        "text": {"format": "markdown", "raw": text},
    })


@mcp.tool()
def get_meeting_outcome_by_id(meeting_id: int, id: int) -> dict[str, Any]:
    """Get a single meeting outcome by ID. (required: meeting_id, id)"""
    return get_client().get_meeting_outcome_by_id(meeting_id, id)


@mcp.tool()
def update_meeting_outcome(
    meeting_id: int,
    id: int,
    text: str | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a meeting outcome. (required: meeting_id, id)"""
    payload: dict[str, Any] = {}
    if text is not None:
        payload["text"] = {"format": "markdown", "raw": text}
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_meeting_outcome(meeting_id, id, payload)


@mcp.tool()
def delete_meeting_outcome(meeting_id: int, id: int) -> dict[str, Any]:
    """Delete a meeting outcome. (required: meeting_id, id)"""
    return get_client().delete_meeting_outcome(meeting_id, id)


# ─── Meeting Section Tools ────────────────────────────────────────────

@mcp.tool()
def create_meeting_section(
    meeting_id: int,
    title: str,
    position: int = 0,
) -> dict[str, Any]:
    """Create a meeting section. (required: meeting_id, title, position)"""
    return get_client().create_meeting_section(meeting_id, {
        "title": title,
        "position": position,
    })


@mcp.tool()
def get_meeting_section_by_id(meeting_id: int, id: int) -> dict[str, Any]:
    """Get a single meeting section by ID. (required: meeting_id, id)"""
    return get_client().get_meeting_section_by_id(meeting_id, id)


@mcp.tool()
def update_meeting_section(
    meeting_id: int,
    id: int,
    title: str | None = None,
    position: int | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a meeting section. (required: meeting_id, id)"""
    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if position is not None:
        payload["position"] = position
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_meeting_section(meeting_id, id, payload)


@mcp.tool()
def delete_meeting_section(meeting_id: int, id: int) -> dict[str, Any]:
    """Delete a meeting section. (required: meeting_id, id)"""
    return get_client().delete_meeting_section(meeting_id, id)


# ─── Recurring Meeting Tools ──────────────────────────────────────────

@mcp.tool()
def list_recurring_meetings(
    page_size: int = 20,
    offset: int = 1,
    project_id: int | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List recurring meetings (paginated). (required: none)"""
    import json as _json
    filters = None
    if project_id is not None:
        filters = _json.dumps([{"project": {"operator": "=", "values": [str(project_id)]}}])
    return get_client().list_recurring_meetings(
        page_size=page_size, offset=offset, filters=filters,
        include_all_fields=include_all_fields
    )


@mcp.tool()
def create_recurring_meeting(
    project_id: int,
    title: str,
    frequency: str,
    start_time: str,
    end_time: str,
    days: list[int] | None = None,
    interval_value: int = 1,
    count_limit: int | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Create a recurring meeting. (required: project_id, title, frequency, start_time, end_time)"""
    payload: dict[str, Any] = {
        "title": title,
        "frequency": frequency,
        "_links": {"project": {"href": f"/api/v3/projects/{project_id}"}},
        "start_time": start_time,
        "end_time": end_time,
        "intervalValue": interval_value,
    }
    if days is not None:
        payload["days"] = days
    if count_limit is not None:
        payload["countLimit"] = count_limit
    if end_date is not None:
        payload["endDate"] = end_date
    return get_client().create_recurring_meeting(payload)


@mcp.tool()
def get_recurring_meeting_by_id(id: int) -> dict[str, Any]:
    """Get a single recurring meeting by ID. (required: id)"""
    return get_client().get_recurring_meeting_by_id(id)


@mcp.tool()
def update_recurring_meeting(
    id: int,
    title: str | None = None,
    frequency: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    interval_value: int | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a recurring meeting. (required: id)"""
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
    return get_client().update_recurring_meeting(id, payload)


@mcp.tool()
def delete_recurring_meeting(id: int) -> dict[str, Any]:
    """Delete a recurring meeting. (required: id)"""
    return get_client().delete_recurring_meeting(id)


# ─── Time Entry Tools ─────────────────────────────────────────────────

@mcp.tool()
def list_time_entries(
    page_size: int = 20,
    offset: int = 1,
    project_id: int | None = None,
    work_package_id: int | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List time entries (paginated). (required: none)"""
    import json as _json
    filters: list[dict[str, Any]] = []
    if project_id is not None:
        filters.append({"project": {"operator": "=", "values": [str(project_id)]}})
    if work_package_id is not None:
        filters.append({"workPackage": {"operator": "=", "values": [str(work_package_id)]}})
    filter_str = _json.dumps(filters) if filters else None
    return get_client().list_time_entries(
        page_size=page_size, offset=offset, filters=filter_str,
        include_all_fields=include_all_fields
    )


@mcp.tool()
def create_time_entry(
    project_id: int,
    hours: str,
    work_package_id: int | None = None,
    activity_id: int | None = None,
    spent_on: str | None = None,
    comment: str = "",
) -> dict[str, Any]:
    """Create a time entry. (required: project_id, hours)"""
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
    return get_client().create_time_entry(payload)


@mcp.tool()
def get_time_entry_by_id(id: int) -> dict[str, Any]:
    """Get a single time entry by ID. (required: id)"""
    return get_client().get_time_entry_by_id(id)


@mcp.tool()
def update_time_entry(
    id: int,
    hours: str | None = None,
    spent_on: str | None = None,
    comment: str | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a time entry. (required: id)"""
    payload: dict[str, Any] = {}
    if hours is not None:
        payload["hours"] = hours
    if spent_on is not None:
        payload["spentOn"] = spent_on
    if comment is not None:
        payload["comment"] = {"format": "markdown", "raw": comment}
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_time_entry(id, payload)


@mcp.tool()
def delete_time_entry(id: int) -> dict[str, Any]:
    """Delete a time entry. (required: id)"""
    return get_client().delete_time_entry(id)


# ─── News Tools ───────────────────────────────────────────────────────

@mcp.tool()
def list_news(
    page_size: int = 20,
    offset: int = 1,
    project_id: int | None = None,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List news items (paginated). (required: none)"""
    import json as _json
    filters = None
    if project_id is not None:
        filters = _json.dumps([{"project": {"operator": "=", "values": [str(project_id)]}}])
    return get_client().list_news(
        page_size=page_size, offset=offset, filters=filters,
        include_all_fields=include_all_fields
    )


@mcp.tool()
def create_news(
    project_id: int,
    title: str,
    summary: str = "",
    description: str = "",
) -> dict[str, Any]:
    """Create a news item. (required: project_id, title)"""
    payload: dict[str, Any] = {
        "title": title,
        "_links": {"project": {"href": f"/api/v3/projects/{project_id}"}},
    }
    if summary:
        payload["summary"] = summary
    if description:
        payload["description"] = {"format": "markdown", "raw": description}
    return get_client().create_news(payload)


@mcp.tool()
def get_news_by_id(id: int) -> dict[str, Any]:
    """Get a single news item by ID. (required: id)"""
    return get_client().get_news_by_id(id)


@mcp.tool()
def update_news(
    id: int,
    title: str | None = None,
    summary: str | None = None,
    description: str | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a news item. (required: id)"""
    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if summary is not None:
        payload["summary"] = summary
    if description is not None:
        payload["description"] = {"format": "markdown", "raw": description}
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_news(id, payload)


@mcp.tool()
def delete_news(id: int) -> dict[str, Any]:
    """Delete a news item. (required: id)"""
    return get_client().delete_news(id)


# ─── Grid Tools ───────────────────────────────────────────────────────

@mcp.tool()
def list_grids(
    page_size: int = 20,
    offset: int = 1,
    include_all_fields: bool = False,
) -> dict[str, Any]:
    """List grids (paginated). (required: none)"""
    return get_client().list_grids(
        page_size=page_size, offset=offset, include_all_fields=include_all_fields
    )


@mcp.tool()
def create_grid(
    page: str,
    row_count: int = 3,
    column_count: int = 2,
    scope_href: str | None = None,
) -> dict[str, Any]:
    """Create a grid. (required: page). Optional: scope_href like '/projects/demo-project/boards'"""
    payload: dict[str, Any] = {
        "name": page,
        "rowCount": row_count,
        "columnCount": column_count,
        "options": {},
        "widgets": [],
    }
    if scope_href:
        payload["_links"] = {"scope": {"href": scope_href, "type": "text/html"}}
    return get_client().create_grid(payload)


@mcp.tool()
def get_grid_by_id(id: int) -> dict[str, Any]:
    """Get a single grid by ID. (required: id)"""
    return get_client().get_grid_by_id(id)


@mcp.tool()
def update_grid(
    id: int,
    page: str | None = None,
    row_count: int | None = None,
    widgets: list[dict[str, Any]] | None = None,
    lock_version: int | None = None,
) -> dict[str, Any]:
    """Update a grid. (required: id)"""
    payload: dict[str, Any] = {}
    if page is not None:
        payload["page"] = page
    if row_count is not None:
        payload["rowCount"] = row_count
    if widgets is not None:
        payload["widgets"] = widgets
    if lock_version is not None:
        payload["lockVersion"] = lock_version
    return get_client().update_grid(id, payload)


@mcp.tool()
def delete_grid(id: int) -> dict[str, Any]:
    """Delete a grid. (required: id)"""
    return get_client().delete_grid(id)


# ─── Health check ─────────────────────────────────────────────────────

@mcp.tool()
def health_check() -> dict[str, str]:
    """Basic server health check. (required: none)"""
    return {"status": "ok"}


# ─── Main entry point ─────────────────────────────────────────────────

def main() -> None:
    import uvicorn
    port = MCP_SERVER_PORT
    print(f"Starting OpenProject MCP server on port {port}")
    uvicorn.run(mcp.http_app(), host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()