"""OpenProject API v3 client."""

from __future__ import annotations

import base64
import datetime as dt
import os
import re
from typing import Any

import httpx


def _normalize_datetime(value: str) -> str:
    """Validate and convert ISO 8601 datetime with explicit UTC offset."""
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$', value):
        parsed = dt.datetime.fromisoformat(value)
        parsed = parsed.astimezone(dt.timezone.utc)
        return parsed.strftime('%Y-%m-%d %H:%M:%S')
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', value):
        raise ValueError(
            f"Invalid datetime: {value}. Timezone offset is required. "
            "Must use format: 2026-06-22T15:00:00-04:00"
        )
    return value


_DATETIME_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?Z$'
)


def _postprocess_dates(data: Any) -> Any:
    """Recursively walk response data and convert Z-suffix datetimes to explicit offset ISO 8601."""
    if isinstance(data, dict):
        return {k: _postprocess_dates(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_postprocess_dates(item) for item in data]
    if isinstance(data, str):
        m = _DATETIME_RE.match(data)
        if m:
            return f"{m.group(1)}T{m.group(2)}+00:00"
    return data


ALLOW_ALL_AGGREGATE = os.environ.get("ALLOW_ALL_AGGREGATE", "false").lower() == "true"

COMMON_FIELDS: dict[str, set[str]] = {
    "work_package": {"id", "subject", "lockVersion"},
    "project": {"id", "name", "identifier", "active", "public"},
    "version": {"id", "name", "status", "sharing"},
    "membership": {"id"},
    "user": {"id", "login", "firstName", "lastName", "email", "admin"},
    "group": {"id", "name"},
    "principal": {"id", "name"},
    "meeting": {"id", "title", "lockVersion", "state", "notify"},
    "meeting_agenda_item": {"id", "title", "item_type", "duration_in_minutes"},
    "meeting_section": {"id", "name", "position"},
    "recurring_meeting": {"id", "title", "frequency", "interval_value"},
    "time_entry": {"id", "hours"},
    "news": {"id", "title", "summary"},
    "grid": {"id", "rowCount", "columnCount"},
    "status": {"id", "name", "isDefault", "isClosed"},
    "type": {"id", "name", "isDefault"},
    "priority": {"id", "name", "isDefault"},
    "role": {"id", "name"},
    "category": {"id", "name"},
    "wiki_page": {"id", "title"},
    "budget": {"id", "subject"},
    "cost_type": {"id", "name", "unit"},
    "notification": {"id", "reason", "readIAN"},
    "day": {"id", "date", "name", "working"},
    "non_working_day": {"id", "date", "name"},
    "week_day": {"id", "day", "name", "working"},
    "attachment": {"id", "fileName", "fileSize", "mimeType"},
    "document": {"id", "title"},
    "emoji_reaction": {"id", "reaction", "userId"},
    "reminder": {"id", "note"},
}

LINK_FIELDS: dict[str, set[str]] = {
    "work_package": {"project", "type", "status", "priority", "assignee", "responsible", "version", "parent", "category", "author"},
    "project": {"status"},
    "version": {"definingProject"},
    "membership": {"project", "principal"},
    "meeting": {"project", "author", "recurringMeeting"},
    "recurring_meeting": {"project"},
    "time_entry": {"workPackage", "project"},
    "news": {"project", "author"},
    "category": {"project"},
    "wiki_page": {"project"},
    "budget": {"project"},
    "document": {"project", "author"},
}


COLLECTION_KEYS = {"_type", "total", "count", "pageSize", "offset", "_embedded"}


def _filter_fields(data: Any, common_set: set[str], link_set: set[str] | None = None) -> Any:
    """Filter a dict or list of dicts to only the common field set. Also filters _links if link_set provided."""
    if isinstance(data, dict):
        if "_embedded" in data and "elements" in data["_embedded"] and isinstance(data["_embedded"]["elements"], list):
            filtered_elements = _filter_fields(data["_embedded"]["elements"], common_set, link_set)
            result: dict[str, Any] = {k: v for k, v in data.items() if k in COLLECTION_KEYS}
            result["_embedded"] = {"elements": filtered_elements}
            return result
        filtered = {k: v for k, v in data.items() if k in common_set}
        if link_set is not None and "_links" in data and isinstance(data["_links"], dict):
            filtered["_links"] = {}
            for lk, lv in data["_links"].items():
                if lk in link_set:
                    if isinstance(lv, dict) and "title" in lv:
                        filtered["_links"][lk] = {"title": lv["title"]}
                    else:
                        filtered["_links"][lk] = lv
        return filtered
    if isinstance(data, list):
        return [_filter_fields(item, common_set, link_set) for item in data]
    return data


class OpenProjectClient:
    """HTTP client for OpenProject API v3.

    Accepts Bearer token auth (from MCP), converts to Basic auth for the backend.
    The API_KEY env var should be the full base64-encoded 'apikey:{token}' value.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.base_url = os.environ.get(
            "OPENPROJECT_BASE_URL", "http://openproject-api:80"
        )
        raw_key = api_key or os.environ.get("API_KEY", "")
        if raw_key.startswith("Bearer "):
            raw_key = raw_key[7:]
        self.api_key = raw_key

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Basic {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate datetime strings in a request payload."""
        return {k: _normalize_datetime(v) if isinstance(v, str) else v for k, v in payload.items()}

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}/api/v3{path}"
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            resp = client.request(
                method, url, headers=self._headers(), params=params, json=json
            )
        if resp.status_code in (202, 204):
            return {}
        resp.raise_for_status()
        return _postprocess_dates(resp.json())

    def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        return self._request("GET", path, params=params)

    def _post(
        self, path: str, json: dict[str, Any] | None = None
    ) -> Any:
        return self._request("POST", path, json=json)

    def _patch(
        self, path: str, json: dict[str, Any] | None = None
    ) -> Any:
        return self._request("PATCH", path, json=json)

    def _delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    # ─── Work Packages ────────────────────────────────────────────────

    def list_work_packages(
        self,
        page_size: int = 20,
        offset: int = 1,
        filters: str | None = None,
        sort_by: str | None = None,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": page_size, "offset": offset}
        if filters:
            params["filters"] = filters
        if sort_by:
            params["sortBy"] = sort_by
        data = self._get("/work_packages", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["work_package"], LINK_FIELDS.get("work_package"))
        return data

    def create_work_package(self, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._post("/work_packages", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["work_package"], LINK_FIELDS.get("work_package"))
        return data

    def get_work_package_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/work_packages/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["work_package"], LINK_FIELDS.get("work_package"))
        return data

    def update_work_package(
        self, id: int, payload: dict[str, Any], include_all_fields: bool = False
    ) -> dict[str, Any]:
        data = self._patch(f"/work_packages/{id}", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["work_package"], LINK_FIELDS.get("work_package"))
        return data

    def delete_work_package(self, id: int) -> dict[str, Any]:
        self._delete(f"/work_packages/{id}")
        return {"message": "Work package successfully deleted."}

    def get_work_package_activities(
        self, id: int, page_size: int = 20, offset: int = 1
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        return self._get(f"/work_packages/{id}/activities", params=params)

    def add_work_package_comment(
        self, id: int, comment: str
    ) -> dict[str, Any]:
        return self._post(
            f"/work_packages/{id}/activities",
            json={"comment": {"raw": comment}},
        )

    def get_work_package_relations(self, id: int) -> dict[str, Any]:
        return self._get(f"/work_packages/{id}/relations")

    def create_work_package_relation(
        self, id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._post(f"/work_packages/{id}/relations", json=payload)

    def get_work_package_watchers(self, id: int) -> dict[str, Any]:
        return self._get(f"/work_packages/{id}/watchers")

    def add_work_package_watcher(
        self, id: int, user_id: int
    ) -> dict[str, Any]:
        return self._post(
            f"/work_packages/{id}/watchers",
            json={"user": {"href": f"/api/v3/users/{user_id}"}},
        )

    def remove_work_package_watcher(
        self, id: int, user_id: int
    ) -> dict[str, Any]:
        return self._delete(f"/work_packages/{id}/watchers/{user_id}")

    def list_work_package_attachments(
        self, id: int, page_size: int = 20, offset: int = 1
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        return self._get(f"/work_packages/{id}/attachments", params=params)

    # ─── Projects ─────────────────────────────────────────────────────

    def list_projects(
        self,
        page_size: int = 20,
        offset: int = 1,
        filters: str | None = None,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": page_size, "offset": offset}
        if filters:
            params["filters"] = filters
        data = self._get("/projects", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["project"], LINK_FIELDS.get("project"))
        return data

    def create_project(self, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._post("/projects", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["project"], LINK_FIELDS.get("project"))
        return data

    def get_project_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/projects/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["project"], LINK_FIELDS.get("project"))
        return data

    def update_project(self, id: int, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._patch(f"/projects/{id}", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["project"], LINK_FIELDS.get("project"))
        return data

    def delete_project(self, id: int) -> dict[str, Any]:
        self._delete(f"/projects/{id}")
        return {"message": "Project successfully deleted."}

    def copy_project(self, id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post(f"/projects/{id}/copy", json=payload)

    # ─── Versions ─────────────────────────────────────────────────────

    def list_versions(
        self,
        page_size: int = 20,
        offset: int = 1,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        data = self._get("/versions", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["version"], LINK_FIELDS.get("version"))
        return data

    def create_version(self, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._post("/versions", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["version"], LINK_FIELDS.get("version"))
        return data

    def get_version_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/versions/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["version"], LINK_FIELDS.get("version"))
        return data

    def update_version(self, id: int, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._patch(f"/versions/{id}", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["version"], LINK_FIELDS.get("version"))
        return data

    def delete_version(self, id: int) -> dict[str, Any]:
        self._delete(f"/versions/{id}")
        return {"message": "Version successfully deleted."}

    # ─── Memberships ──────────────────────────────────────────────────

    def list_memberships(
        self,
        page_size: int = 20,
        offset: int = 1,
        filters: str | None = None,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": page_size, "offset": offset}
        if filters:
            params["filters"] = filters
        data = self._get("/memberships", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["membership"], LINK_FIELDS.get("membership"))
        return data

    def create_membership(self, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._post("/memberships", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["membership"], LINK_FIELDS.get("membership"))
        return data

    def get_membership_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/memberships/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["membership"], LINK_FIELDS.get("membership"))
        return data

    def update_membership(self, id: int, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._patch(f"/memberships/{id}", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["membership"], LINK_FIELDS.get("membership"))
        return data

    def delete_membership(self, id: int) -> dict[str, Any]:
        self._delete(f"/memberships/{id}")
        return {"message": "Membership successfully deleted."}

    # ─── Users ────────────────────────────────────────────────────────

    def list_users(
        self,
        page_size: int = 20,
        offset: int = 1,
        filters: str | None = None,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": page_size, "offset": offset}
        if filters:
            params["filters"] = filters
        data = self._get("/users", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["user"])
        return data

    def get_user_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/users/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["user"])
        return data

    def create_user(self, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._post("/users", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["user"])
        return data

    def update_user(self, id: int, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._patch(f"/users/{id}", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["user"])
        return data

    def delete_user(self, id: int) -> dict[str, Any]:
        self._delete(f"/users/{id}")
        return {"message": "User successfully deleted."}

    # ─── Groups ───────────────────────────────────────────────────────

    def list_groups(
        self,
        page_size: int = 20,
        offset: int = 1,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        data = self._get("/groups", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["group"])
        return data

    def get_group_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/groups/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["group"])
        return data

    def create_group(self, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._post("/groups", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["group"])
        return data

    def update_group(self, id: int, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._patch(f"/groups/{id}", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["group"])
        return data

    def delete_group(self, id: int) -> dict[str, Any]:
        self._delete(f"/groups/{id}")
        return {"message": "Group successfully deleted."}

    # ─── Statuses ─────────────────────────────────────────────────────

    def list_statuses(
        self,
        page_size: int = 20,
        offset: int = 1,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        data = self._get("/statuses", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["status"])
        return data

    def get_status_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/statuses/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["status"])
        return data

    # ─── Types ────────────────────────────────────────────────────────

    def list_types(
        self,
        page_size: int = 20,
        offset: int = 1,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        data = self._get("/types", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["type"])
        return data

    def get_type_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/types/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["type"])
        return data

    # ─── Priorities ───────────────────────────────────────────────────

    def list_priorities(
        self,
        page_size: int = 20,
        offset: int = 1,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        data = self._get("/priorities", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["priority"])
        return data

    def get_priority_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/priorities/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["priority"])
        return data

    # ─── Roles ────────────────────────────────────────────────────────

    def list_roles(
        self,
        page_size: int = 20,
        offset: int = 1,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        data = self._get("/roles", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["role"])
        return data

    def get_role_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/roles/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["role"])
        return data

    # ─── Principals ───────────────────────────────────────────────────

    def list_principals(
        self,
        page_size: int = 20,
        offset: int = 1,
        filters: str | None = None,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": page_size, "offset": offset}
        if filters:
            params["filters"] = filters
        data = self._get("/principals", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["principal"])
        return data

    def get_principal_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/principals/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["principal"])
        return data

    # ─── Categories ───────────────────────────────────────────────────

    def get_category_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/categories/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["category"], LINK_FIELDS.get("category"))
        return data

    def list_project_categories(
        self, project_id: int, page_size: int = 20, offset: int = 1, include_all_fields: bool = False
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        data = self._get(f"/projects/{project_id}/categories", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["category"], LINK_FIELDS.get("category"))
        return data

    # ─── Wiki Pages ───────────────────────────────────────────────────

    def get_wiki_page_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/wiki_pages/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["wiki_page"], LINK_FIELDS.get("wiki_page"))
        return data

    # ─── Budgets ──────────────────────────────────────────────────────

    def get_budget_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/budgets/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["budget"], LINK_FIELDS.get("budget"))
        return data

    def list_project_budgets(
        self, project_id: int, page_size: int = 20, offset: int = 1, include_all_fields: bool = False
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        data = self._get(f"/projects/{project_id}/budgets", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["budget"], LINK_FIELDS.get("budget"))
        return data

    # ─── Cost Types ───────────────────────────────────────────────────

    def get_cost_type_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/cost_types/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["cost_type"])
        return data

    # ─── Notifications ────────────────────────────────────────────────

    def list_notifications(
        self,
        page_size: int = 20,
        offset: int = 1,
        filters: str | None = None,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": page_size, "offset": offset}
        if filters:
            params["filters"] = filters
        data = self._get("/notifications", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["notification"])
        return data

    def get_notification_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/notifications/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["notification"])
        return data

    # ─── Days / Calendar ──────────────────────────────────────────────

    def list_days(
        self,
        page_size: int = 20,
        offset: int = 1,
        filters: str | None = None,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": page_size, "offset": offset}
        if filters:
            params["filters"] = filters
        data = self._get("/days", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["day"])
        return data

    def list_non_working_days(
        self,
        page_size: int = 20,
        offset: int = 1,
        filters: str | None = None,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": page_size, "offset": offset}
        if filters:
            params["filters"] = filters
        data = self._get("/days/non_working", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["non_working_day"])
        return data

    def get_non_working_day_by_date(self, date: str, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/days/non_working/{date}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["non_working_day"])
        return data

    def list_week_days(
        self,
        page_size: int = 20,
        offset: int = 1,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        data = self._get("/days/week", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["week_day"])
        return data

    def get_week_day_by_number(self, day: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/days/week/{day}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["week_day"])
        return data

    # ─── Attachments (metadata only) ─────────────────────────────────

    def get_attachment_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/attachments/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["attachment"])
        return data

    # ─── Documents ────────────────────────────────────────────────────

    def list_documents(
        self,
        page_size: int = 20,
        offset: int = 1,
        filters: str | None = None,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": page_size, "offset": offset}
        if filters:
            params["filters"] = filters
        data = self._get("/documents", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["document"], LINK_FIELDS.get("document"))
        return data

    def get_document_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/documents/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["document"], LINK_FIELDS.get("document"))
        return data

    def update_document(self, id: int, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._patch(f"/documents/{id}", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["document"], LINK_FIELDS.get("document"))
        return data

    # ─── Emoji Reactions ──────────────────────────────────────────────

    def list_emoji_reactions(self, activity_id: int) -> dict[str, Any]:
        return self._get(f"/activities/{activity_id}/emoji_reactions")

    def toggle_emoji_reaction(
        self, activity_id: int, reaction: str
    ) -> dict[str, Any]:
        return self._patch(
            f"/activities/{activity_id}/emoji_reactions",
            json={"reaction": reaction},
        )

    # ─── Reminders ────────────────────────────────────────────────────

    def create_reminder(self, work_package_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post(f"/work_packages/{work_package_id}/reminders", json=payload)

    def list_reminders(
        self,
        page_size: int = 20,
        offset: int = 1,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        data = self._get("/reminders", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["reminder"])
        return data

    def update_reminder(self, id: int, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._patch(f"/reminders/{id}", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["reminder"])
        return data

    def delete_reminder(self, id: int) -> dict[str, Any]:
        self._delete(f"/reminders/{id}")
        return {"message": "Reminder successfully deleted."}

    # ─── Meetings ─────────────────────────────────────────────────────

    def list_meetings(
        self,
        page_size: int = 20,
        offset: int = 1,
        filters: str | None = None,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": page_size, "offset": offset}
        if filters:
            params["filters"] = filters
        data = self._get("/meetings", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["meeting"], LINK_FIELDS.get("meeting"))
        return data

    def create_meeting(self, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._post("/meetings", json=self._normalize_payload(payload))
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["meeting"], LINK_FIELDS.get("meeting"))
        return data

    def get_meeting_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/meetings/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["meeting"], LINK_FIELDS.get("meeting"))
        return data

    def update_meeting(self, id: int, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._patch(f"/meetings/{id}", json=self._normalize_payload(payload))
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["meeting"], LINK_FIELDS.get("meeting"))
        return data

    def delete_meeting(self, id: int) -> dict[str, Any]:
        self._delete(f"/meetings/{id}")
        return {"message": "Meeting successfully deleted."}

    def list_meeting_agenda_items(self, meeting_id: int) -> dict[str, Any]:
        return self._get(f"/meetings/{meeting_id}/agenda_items")

    def list_meeting_sections(self, meeting_id: int) -> dict[str, Any]:
        return self._get(f"/meetings/{meeting_id}/sections")

    # ─── Meeting Agenda Items ─────────────────────────────────────────

    def create_meeting_agenda_item(self, meeting_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post(f"/meetings/{meeting_id}/agenda_items", json=payload)

    def get_meeting_agenda_item_by_id(self, meeting_id: int, id: int) -> dict[str, Any]:
        return self._get(f"/meetings/{meeting_id}/agenda_items/{id}")

    def update_meeting_agenda_item(
        self, meeting_id: int, id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._patch(f"/meetings/{meeting_id}/agenda_items/{id}", json=payload)

    def delete_meeting_agenda_item(self, meeting_id: int, id: int) -> dict[str, Any]:
        self._delete(f"/meetings/{meeting_id}/agenda_items/{id}")
        return {"message": "Agenda item successfully deleted."}

    # ─── Meeting Sections ─────────────────────────────────────────────

    def create_meeting_section(self, meeting_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post(f"/meetings/{meeting_id}/sections", json=payload)

    def get_meeting_section_by_id(self, meeting_id: int, id: int) -> dict[str, Any]:
        return self._get(f"/meetings/{meeting_id}/sections/{id}")

    def update_meeting_section(
        self, meeting_id: int, id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._patch(f"/meetings/{meeting_id}/sections/{id}", json=payload)

    def delete_meeting_section(self, meeting_id: int, id: int) -> dict[str, Any]:
        self._delete(f"/meetings/{meeting_id}/sections/{id}")
        return {"message": "Section successfully deleted."}

    # ─── Time Entries ─────────────────────────────────────────────────

    def list_time_entries(
        self,
        page_size: int = 20,
        offset: int = 1,
        filters: str | None = None,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": page_size, "offset": offset}
        if filters:
            params["filters"] = filters
        data = self._get("/time_entries", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["time_entry"], LINK_FIELDS.get("time_entry"))
        return data

    def create_time_entry(self, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._post("/time_entries", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["time_entry"], LINK_FIELDS.get("time_entry"))
        return data

    def get_time_entry_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/time_entries/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["time_entry"], LINK_FIELDS.get("time_entry"))
        return data

    def update_time_entry(self, id: int, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._patch(f"/time_entries/{id}", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["time_entry"], LINK_FIELDS.get("time_entry"))
        return data

    def delete_time_entry(self, id: int) -> dict[str, Any]:
        self._delete(f"/time_entries/{id}")
        return {"message": "Time entry successfully deleted."}

    # ─── News ─────────────────────────────────────────────────────────

    def list_news(
        self,
        page_size: int = 20,
        offset: int = 1,
        filters: str | None = None,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": page_size, "offset": offset}
        if filters:
            params["filters"] = filters
        data = self._get("/news", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["news"], LINK_FIELDS.get("news"))
        return data

    def create_news(self, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._post("/news", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["news"], LINK_FIELDS.get("news"))
        return data

    def get_news_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/news/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["news"], LINK_FIELDS.get("news"))
        return data

    def update_news(self, id: int, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._patch(f"/news/{id}", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["news"], LINK_FIELDS.get("news"))
        return data

    def delete_news(self, id: int) -> dict[str, Any]:
        self._delete(f"/news/{id}")
        return {"message": "News successfully deleted."}

    # ─── Recurring Meetings ───────────────────────────────────────────

    def list_recurring_meetings(
        self,
        page_size: int = 20,
        offset: int = 1,
        filters: str | None = None,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": page_size, "offset": offset}
        if filters:
            params["filters"] = filters
        data = self._get("/recurring_meetings", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["recurring_meeting"], LINK_FIELDS.get("recurring_meeting"))
        return data

    def create_recurring_meeting(self, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._post("/recurring_meetings", json=self._normalize_payload(payload))
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["recurring_meeting"], LINK_FIELDS.get("recurring_meeting"))
        return data

    def get_recurring_meeting_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/recurring_meetings/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["recurring_meeting"], LINK_FIELDS.get("recurring_meeting"))
        return data

    def update_recurring_meeting(
        self, id: int, payload: dict[str, Any], include_all_fields: bool = False
    ) -> dict[str, Any]:
        data = self._patch(f"/recurring_meetings/{id}", json=self._normalize_payload(payload))
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["recurring_meeting"], LINK_FIELDS.get("recurring_meeting"))
        return data

    def delete_recurring_meeting(self, id: int) -> dict[str, Any]:
        self._delete(f"/recurring_meetings/{id}")
        return {"message": "Recurring meeting successfully deleted."}

    # ─── Grids ────────────────────────────────────────────────────────

    def list_grids(
        self,
        page_size: int = 20,
        offset: int = 1,
        filters: str | None = None,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": page_size, "offset": offset}
        if filters:
            params["filters"] = filters
        data = self._get("/grids", params=params)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["grid"])
        return data

    def create_grid(self, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._post("/grids", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["grid"])
        return data

    def get_grid_by_id(self, id: int, include_all_fields: bool = False) -> dict[str, Any]:
        data = self._get(f"/grids/{id}")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["grid"])
        return data

    def update_grid(self, id: int, payload: dict[str, Any], include_all_fields: bool = False) -> dict[str, Any]:
        data = self._patch(f"/grids/{id}", json=payload)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["grid"])
        return data

    def delete_grid(self, id: int) -> dict[str, Any]:
        self._delete(f"/grids/{id}")
        return {"message": "Grid successfully deleted."}

    # ─── Job Status ─────────────────────────────────────────────────

    def get_job_status(self, job_id: str) -> dict[str, Any]:
        return self._get(f"/job_statuses/{job_id}")