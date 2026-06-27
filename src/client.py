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
        return resp.json()

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
        return self._get("/work_packages", params=params)

    def create_work_package(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/work_packages", json=payload)

    def get_work_package_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/work_packages/{id}")

    def update_work_package(
        self, id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._patch(f"/work_packages/{id}", json=payload)

    def delete_work_package(self, id: int) -> dict[str, Any]:
        return self._delete(f"/work_packages/{id}")

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
        return self._get("/projects", params=params)

    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/projects", json=payload)

    def get_project_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/projects/{id}")

    def update_project(self, id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"/projects/{id}", json=payload)

    def delete_project(self, id: int) -> dict[str, Any]:
        return self._delete(f"/projects/{id}")

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
        return self._get("/versions", params=params)

    def create_version(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/versions", json=payload)

    def get_version_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/versions/{id}")

    def update_version(self, id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"/versions/{id}", json=payload)

    def delete_version(self, id: int) -> dict[str, Any]:
        return self._delete(f"/versions/{id}")

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
        return self._get("/memberships", params=params)

    def create_membership(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/memberships", json=payload)

    def get_membership_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/memberships/{id}")

    def update_membership(self, id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"/memberships/{id}", json=payload)

    def delete_membership(self, id: int) -> dict[str, Any]:
        return self._delete(f"/memberships/{id}")

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
        return self._get("/users", params=params)

    def get_user_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/users/{id}")

    def create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/users", json=payload)

    def update_user(self, id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"/users/{id}", json=payload)

    def delete_user(self, id: int) -> dict[str, Any]:
        return self._delete(f"/users/{id}")

    # ─── Groups ───────────────────────────────────────────────────────

    def list_groups(
        self,
        page_size: int = 20,
        offset: int = 1,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        return self._get("/groups", params=params)

    def get_group_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/groups/{id}")

    def create_group(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/groups", json=payload)

    def update_group(self, id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"/groups/{id}", json=payload)

    def delete_group(self, id: int) -> dict[str, Any]:
        return self._delete(f"/groups/{id}")

    # ─── Statuses ─────────────────────────────────────────────────────

    def list_statuses(
        self,
        page_size: int = 20,
        offset: int = 1,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        return self._get("/statuses", params=params)

    def get_status_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/statuses/{id}")

    # ─── Types ────────────────────────────────────────────────────────

    def list_types(
        self,
        page_size: int = 20,
        offset: int = 1,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        return self._get("/types", params=params)

    def get_type_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/types/{id}")

    # ─── Priorities ───────────────────────────────────────────────────

    def list_priorities(
        self,
        page_size: int = 20,
        offset: int = 1,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        return self._get("/priorities", params=params)

    def get_priority_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/priorities/{id}")

    # ─── Roles ────────────────────────────────────────────────────────

    def list_roles(
        self,
        page_size: int = 20,
        offset: int = 1,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        return self._get("/roles", params=params)

    def get_role_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/roles/{id}")

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
        return self._get("/principals", params=params)

    def get_principal_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/principals/{id}")

    # ─── Categories ───────────────────────────────────────────────────

    def get_category_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/categories/{id}")

    def list_project_categories(
        self, project_id: int, page_size: int = 20, offset: int = 1
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        return self._get(f"/projects/{project_id}/categories", params=params)

    # ─── Wiki Pages ───────────────────────────────────────────────────

    def get_wiki_page_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/wiki_pages/{id}")

    # ─── Budgets ──────────────────────────────────────────────────────

    def get_budget_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/budgets/{id}")

    def list_project_budgets(
        self, project_id: int, page_size: int = 20, offset: int = 1
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        return self._get(f"/projects/{project_id}/budgets", params=params)

    # ─── Cost Types ───────────────────────────────────────────────────

    def get_cost_type_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/cost_types/{id}")

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
        return self._get("/notifications", params=params)

    def get_notification_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/notifications/{id}")

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
        return self._get("/days", params=params)

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
        return self._get("/days/non_working", params=params)

    def get_non_working_day_by_date(self, date: str) -> dict[str, Any]:
        return self._get(f"/days/non_working/{date}")

    def list_week_days(
        self,
        page_size: int = 20,
        offset: int = 1,
        include_all_fields: bool = False,
    ) -> dict[str, Any]:
        params = {"pageSize": page_size, "offset": offset}
        return self._get("/days/week", params=params)

    def get_week_day_by_number(self, day: int) -> dict[str, Any]:
        return self._get(f"/days/week/{day}")

    # ─── Attachments (metadata only) ─────────────────────────────────

    def get_attachment_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/attachments/{id}")

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
        return self._get("/documents", params=params)

    def get_document_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/documents/{id}")

    def update_document(self, id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"/documents/{id}", json=payload)

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
        return self._get("/reminders", params=params)

    def update_reminder(self, id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"/reminders/{id}", json=payload)

    def delete_reminder(self, id: int) -> dict[str, Any]:
        return self._delete(f"/reminders/{id}")

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
        return self._get("/meetings", params=params)

    def create_meeting(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/meetings", json=self._normalize_payload(payload))

    def get_meeting_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/meetings/{id}")

    def update_meeting(self, id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"/meetings/{id}", json=self._normalize_payload(payload))

    def delete_meeting(self, id: int) -> dict[str, Any]:
        return self._delete(f"/meetings/{id}")

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
        return self._delete(f"/meetings/{meeting_id}/agenda_items/{id}")

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
        return self._delete(f"/meetings/{meeting_id}/sections/{id}")

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
        return self._get("/time_entries", params=params)

    def create_time_entry(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/time_entries", json=payload)

    def get_time_entry_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/time_entries/{id}")

    def update_time_entry(self, id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"/time_entries/{id}", json=payload)

    def delete_time_entry(self, id: int) -> dict[str, Any]:
        return self._delete(f"/time_entries/{id}")

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
        return self._get("/news", params=params)

    def create_news(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/news", json=payload)

    def get_news_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/news/{id}")

    def update_news(self, id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"/news/{id}", json=payload)

    def delete_news(self, id: int) -> dict[str, Any]:
        return self._delete(f"/news/{id}")

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
        return self._get("/recurring_meetings", params=params)

    def create_recurring_meeting(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/recurring_meetings", json=self._normalize_payload(payload))

    def get_recurring_meeting_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/recurring_meetings/{id}")

    def update_recurring_meeting(
        self, id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._patch(f"/recurring_meetings/{id}", json=self._normalize_payload(payload))

    def delete_recurring_meeting(self, id: int) -> dict[str, Any]:
        return self._delete(f"/recurring_meetings/{id}")

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
        return self._get("/grids", params=params)

    def create_grid(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/grids", json=payload)

    def get_grid_by_id(self, id: int) -> dict[str, Any]:
        return self._get(f"/grids/{id}")

    def update_grid(self, id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"/grids/{id}", json=payload)

    def delete_grid(self, id: int) -> dict[str, Any]:
        return self._delete(f"/grids/{id}")

    # ─── Job Status ─────────────────────────────────────────────────

    def get_job_status(self, job_id: str) -> dict[str, Any]:
        return self._get(f"/job_statuses/{job_id}")