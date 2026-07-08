"""OpenProject MCP flat test harness.

Every test runs unconditionally. No SKIP, no if/else in test flow.
Only PASS or FAIL. Assertion logic lives in helper functions.
Unexpected exceptions crash the runner immediately.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import string
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from toon_mcp import toon_to_json


MCP_SERVER_PORT = os.environ.get("MCP_SERVER_PORT", "6893")
API_KEY = os.environ.get("API_KEY", "")
MCP_URL = f"http://localhost:{MCP_SERVER_PORT}/mcp"


def make_name(base: str) -> str:
    rid = getattr(make_name, "_rid", "")
    return f"t{rid}-{base}"


def set_run_id(rid: str) -> None:
    make_name._rid = rid


def gen_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%m%d%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"{ts}{suffix}"


# ─── MCP Session ──────────────────────────────────────────────────────


class MCPSession:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session_id: str | None = None
        self.client = httpx.AsyncClient(timeout=120.0)
        self.base_headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

    async def initialize(self) -> dict[str, Any]:
        resp = await self.client.post(
            MCP_URL,
            json={
                "jsonrpc": "2.0", "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "test-runner", "version": "0.1.0"},
                    "capabilities": {},
                },
                "id": 1,
            },
            headers=self.base_headers,
        )
        for header, value in resp.headers.items():
            if header == "mcp-session-id":
                self.session_id = value
        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            for line in resp.text.split("\n"):
                if line.startswith("data: "):
                    return json.loads(line[6:])
            return {}
        return resp.json()

    async def _send(self, method: str, params: dict[str, Any] | None = None, tool_id: int = 1) -> dict[str, Any]:
        headers = dict(self.base_headers)
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": tool_id}
        resp = await self.client.post(MCP_URL, json=payload, headers=headers)
        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            for line in resp.text.split("\n"):
                if line.startswith("data: "):
                    parsed = json.loads(line[6:])
                    if "id" in parsed:
                        return parsed.get("result", parsed)
                    return parsed
            return {}
        if resp.status_code == 202:
            return {}
        return resp.json()

    async def call_tool(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._send("tools/call", {"name": name, "arguments": args or {}})

    async def list_tools(self) -> dict[str, Any]:
        return await self._send("tools/list")

    async def close(self) -> None:
        await self.client.aclose()


# ─── Data helpers ─────────────────────────────────────────────────────


def is_error(result: dict[str, Any]) -> str | None:
    err = result.get("error")
    if err:
        return json.dumps(err)
    if result.get("isError"):
        return str(result.get("content", result))
    return None


def extract_content(result: dict[str, Any]) -> dict[str, Any]:
    """Extract text content from a tool result. Always returns a dict."""
    content = (result or {}).get("content", [])
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                try:
                    parsed = json.loads(text)
                    return parsed if isinstance(parsed, dict) else {}
                except (json.JSONDecodeError, TypeError):
                    return {}
    return {}


TOON_WRAP_KEYS = ("items", "results", "rows", "tree")


def _decode_toon_val(val: Any) -> Any:
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            return toon_to_json(val)
        except Exception:
            pass
    return val


def get_list_items(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in TOON_WRAP_KEYS:
            if key in data:
                decoded = _decode_toon_val(data[key])
                if isinstance(decoded, list):
                    return decoded
                if isinstance(decoded, dict):
                    if "_embedded" in decoded and "elements" in decoded["_embedded"]:
                        return decoded["_embedded"]["elements"]
                    if "_embedded" in decoded:
                        for v in decoded["_embedded"].values():
                            if isinstance(v, list):
                                return v
                    return [decoded]
        if "_embedded" in data and "elements" in data["_embedded"]:
            return data["_embedded"]["elements"]
        if "_embedded" in data:
            for v in data["_embedded"].values():
                if isinstance(v, list):
                    return v
        return [data]
    return []


def get_first_id(data: Any) -> int | None:
    items = get_list_items(data)
    if items and isinstance(items[0], dict):
        return items[0].get("id")
    return None


def find_match(data: Any, match_field: str, value: str) -> Any | None:
    items = get_list_items(data)
    for item in items:
        if isinstance(item, dict) and item.get(match_field) == value:
            return item
    return None


def first_field(data: Any, field: str) -> Any:
    items = get_list_items(data)
    if items and isinstance(items[0], dict):
        return items[0].get(field)
    return None


def find_project_role(data: Any) -> int | None:
    for item in get_list_items(data):
        name = str((item or {}).get("name", "")).lower()
        if name in ("member", "project admin", "reader"):
            return (item or {}).get("id")
    return None


# ─── TestResult with honest pass/fail ─────────────────────────────────


class TestResult:
    def __init__(self) -> None:
        self.passed: list[tuple[str, str]] = []
        self.failed: list[tuple[str, str, str]] = []

    def p(self, label: str, tool: str) -> None:
        self.passed.append((label, tool))
        print(f"  PASS: {tool} — {label}")

    def f(self, label: str, tool: str, err: str) -> None:
        self.failed.append((label, tool, err))
        print(f"  FAIL: {tool} — {label} — {err.split(chr(10))[0][:120]}")

    def print_phase(self, phase_label: str) -> None:
        print(f"\n## {phase_label}")

    def check_ok(self, result: dict[str, Any], label: str, tool: str) -> dict[str, Any]:
        err = is_error(result)
        if err:
            self.f(label, tool, err)
        else:
            self.p(label, tool)
        return result

    def check_verdel(self, result: dict[str, Any], label: str, tool: str) -> dict[str, Any]:
        """Assert tool returned 'not found' error (verify-delete)."""
        err = is_error(result)
        if err and "not found" in err.lower():
            self.p(label, tool)
        elif err:
            self.f(label, tool, f"Expected 'not found' but got: {err}")
        else:
            self.f(label, tool, "Expected 'not found' but resource exists")
        return result

    def report(self) -> None:
        total = len(self.passed) + len(self.failed)
        print()
        print("=" * 60)
        print(f"# Test Report — OpenProject MCP")
        print(f"# Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"# Server: {MCP_URL}")
        print(f"# Total: {total} tests")
        print()
        print(f"| Status  | Count |")
        print(f"|---------|-------|")
        print(f"| PASSED  | {len(self.passed):>5} |")
        print(f"| FAILED  | {len(self.failed):>5} |")
        print()
        if self.failed:
            print(f"## FAILED ({len(self.failed)})")
            for label, tool, err in self.failed:
                print(f"### {tool} — {label}")
                print(f"- **Error**: {err[:200]}")
            print()


# ─── Main test runner ─────────────────────────────────────────────────


async def async_main() -> None:
    global MCP_URL, MCP_SERVER_PORT
    MCP_SERVER_PORT = os.environ.get("MCP_SERVER_PORT", "6893")
    API_KEY = os.environ.get("API_KEY", "")
    MCP_URL = f"http://localhost:{MCP_SERVER_PORT}/mcp"

    rid = gen_run_id()
    set_run_id(rid)

    print(f"# OpenProject MCP Test Run — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"# Server: {MCP_URL}")
    print(f"# Run ID: {rid}")

    session = MCPSession(API_KEY)
    await session.initialize()

    tools_result = await session.list_tools()
    tool_list = tools_result.get("tools", [])
    print(f"\n## Phase 0 — Initialization")
    print(f"  Discovered {len(tool_list)} tools")

    tr = TestResult()

    # ══════════════════════════════════════════════════════════════════
    # Phase 1: Reference Data
    # ══════════════════════════════════════════════════════════════════
    tr.print_phase("Phase 1 — Reference Data")

    status_id = None
    type_id = None
    priority_id = None
    role_id = None
    user_id = None
    principal_id = None

    r = tr.check_ok(await session.call_tool("list_statuses", {}), "Statuses", "list_statuses")
    status_id = get_first_id(extract_content(r))
    tr.check_ok(await session.call_tool("get_status_by_id", {"id": status_id}), "Statuses", "get_status_by_id")

    r = tr.check_ok(await session.call_tool("list_types", {}), "Types", "list_types")
    type_id = get_first_id(extract_content(r))
    tr.check_ok(await session.call_tool("get_type_by_id", {"id": type_id}), "Types", "get_type_by_id")

    r = tr.check_ok(await session.call_tool("list_priorities", {}), "Priorities", "list_priorities")
    priority_id = get_first_id(extract_content(r))
    tr.check_ok(await session.call_tool("get_priority_by_id", {"id": priority_id}), "Priorities", "get_priority_by_id")

    r = tr.check_ok(await session.call_tool("list_roles", {"page_size": 50}), "Roles", "list_roles")
    role_id = find_project_role(extract_content(r))
    tr.check_ok(await session.call_tool("get_role_by_id", {"id": role_id}), "Roles", "get_role_by_id")

    r = tr.check_ok(await session.call_tool("list_users", {}), "Users", "list_users")
    user_id = get_first_id(extract_content(r))
    tr.check_ok(await session.call_tool("get_user_by_id", {"id": user_id}), "Users", "get_user_by_id")

    r = tr.check_ok(await session.call_tool("list_principals", {}), "Principals", "list_principals")
    principal_id = get_first_id(extract_content(r))
    tr.check_ok(await session.call_tool("get_principal_by_id", {"id": principal_id}), "Principals", "get_principal_by_id")

    # Create persistent project — deleted at end
    ppn = make_name("base")
    r = tr.check_ok(await session.call_tool("create_project", {
        "name": ppn, "identifier": ppn, "description": "Persistent base project", "public": True, "active": True,
    }), "create base project", "create_project")
    persistent_project_id = extract_content(r).get("id")

    # ══════════════════════════════════════════════════════════════════
    # Phase 2: Read-Only Data
    # ══════════════════════════════════════════════════════════════════
    tr.print_phase("Phase 2 — Read-Only Data")

    document_id = None
    nwd_date = None

    tr.check_ok(await session.call_tool("list_notifications", {}), "list_notifications", "list_notifications")
    r = tr.check_ok(await session.call_tool("list_documents", {}), "list_documents", "list_documents")
    document_id = get_first_id(extract_content(r))
    tr.check_ok(await session.call_tool("list_reminders", {}), "list_reminders", "list_reminders")
    tr.check_ok(await session.call_tool("list_days", {}), "list_days", "list_days")
    r = tr.check_ok(await session.call_tool("list_non_working_days", {}), "list_non_working_days", "list_non_working_days")
    first_nwd = get_first_id(extract_content(r))
    tr.check_ok(await session.call_tool("list_week_days", {}), "list_week_days", "list_week_days")
    tr.check_ok(await session.call_tool("health_check", {}), "health_check", "health_check")

    tr.check_ok(await session.call_tool("get_document_by_id", {"id": document_id}), "get document", "get_document_by_id")
    tr.check_ok(await session.call_tool("update_document", {"id": document_id}), "update document", "update_document")

    nwd_date = first_field(extract_content(r), "date")
    tr.check_ok(await session.call_tool("get_non_working_day_by_date", {"date": nwd_date}), "get non-working day", "get_non_working_day_by_date")

    # Fixed data tests
    tr.check_ok(await session.call_tool("get_week_day_by_number", {"day": 1}), "get_week_day_mon", "get_week_day_by_number")
    tr.check_ok(await session.call_tool("get_week_day_by_number", {"day": 7}), "get_week_day_sun", "get_week_day_by_number")
    tr.check_ok(await session.call_tool("get_wiki_page_by_id", {"id": 1}), "get_wiki_page_by_id", "get_wiki_page_by_id")
    tr.check_ok(await session.call_tool("get_attachment_by_id", {"id": 1}), "get_attachment_by_id", "get_attachment_by_id")

    tr.check_ok(await session.call_tool("get_cost_type_by_id", {"id": 1}), "get cost type", "get_cost_type_by_id")

    # Paginated list tests
    tr.check_ok(await session.call_tool("list_projects", {"page_size": 5, "offset": 1}), "list_projects_paged", "list_projects")
    tr.check_ok(await session.call_tool("list_work_packages", {"page_size": 5}), "list_work_packages_paged", "list_work_packages")
    tr.check_ok(await session.call_tool("list_versions", {"page_size": 5}), "list_versions_paged", "list_versions")
    tr.check_ok(await session.call_tool("list_memberships", {"page_size": 5}), "list_memberships_paged", "list_memberships")
    tr.check_ok(await session.call_tool("list_meetings", {"page_size": 5}), "list_meetings_paged", "list_meetings")
    tr.check_ok(await session.call_tool("list_time_entries", {"page_size": 5}), "list_time_entries_paged", "list_time_entries")
    tr.check_ok(await session.call_tool("list_news", {"page_size": 5}), "list_news_paged", "list_news")
    tr.check_ok(await session.call_tool("list_grids", {"page_size": 5}), "list_grids_paged", "list_grids")
    tr.check_ok(await session.call_tool("list_users", {"page_size": 5}), "list_users_paged", "list_users")
    tr.check_ok(await session.call_tool("list_groups", {"page_size": 5}), "list_groups_paged", "list_groups")
    tr.check_ok(await session.call_tool("list_principals", {"page_size": 5}), "list_principals_paged", "list_principals")

    # Date range tests
    tr.check_ok(await session.call_tool("list_days", {"date_from": "2026-06-01", "date_to": "2026-06-30"}), "get_days_by_range", "list_days")
    tr.check_ok(await session.call_tool("list_non_working_days", {"date_from": "2026-06-01", "date_to": "2026-06-01"}), "list_non_working_empty", "list_non_working_days")

    # ══════════════════════════════════════════════════════════════════
    # Phase 3: CRUD Cycles
    # ══════════════════════════════════════════════════════════════════
    tr.print_phase("Phase 3 — CRUD Cycles")

    # ────────── PROJECT CRUD ──────────
    pn = make_name("project")
    r = tr.check_ok(await session.call_tool("create_project", {
        "name": pn, "identifier": pn, "description": "Test", "public": True, "active": True,
    }), "create", "create_project")
    pid = extract_content(r).get("id")

    tr.check_ok(await session.call_tool("list_projects", {}), "list", "list_projects")
    tr.check_ok(await session.call_tool("get_project_by_id", {"id": pid}), "get", "get_project_by_id")

    # ── Copy test ──
    cpy_name = pn + "-cpy"
    cr = tr.check_ok(await session.call_tool("copy_project", {
        "id": pid, "name": cpy_name, "identifier": pn + "_cpy",
    }), "copy", "copy_project")
    job_id = extract_content(cr).get("jobId")

    jr = cr
    for _ in range(30):
        await asyncio.sleep(1)
        jr = await session.call_tool("get_job_status", {"job_id": job_id})

    tr.check_ok(jr, "copy job complete", "get_job_status")

    cpf = None
    for _ in range(10):
        await asyncio.sleep(1)
        cpf = find_match(extract_content(await session.call_tool("list_projects", {"page_size": 100})), "name", cpy_name)

    tr.check_ok(await session.call_tool("get_project_by_id", {"id": (cpf or {}).get("id")}), "get copy", "get_project_by_id")
    tr.check_ok(await session.call_tool("delete_project", {"id": (cpf or {}).get("id")}), "delete copy", "delete_project")

    tr.check_ok(await session.call_tool("delete_project", {"id": pid}), "delete", "delete_project")
    await asyncio.sleep(0.3)
    tr.check_verdel(await session.call_tool("get_project_by_id", {"id": pid}), "verify-delete", "get_project_by_id")

    # ── Update test (separate project) ──
    pn2 = make_name("upd")
    r2 = tr.check_ok(await session.call_tool("create_project", {
        "name": pn2, "identifier": pn2, "description": "Update test", "public": True, "active": True,
    }), "create upd project", "create_project")
    pid2 = extract_content(r2).get("id")

    g2 = tr.check_ok(await session.call_tool("get_project_by_id", {"id": pid2}), "get lock", "get_project_by_id")
    gd2 = extract_content(g2)
    up2 = {"id": pid2, "name": "upd-" + pn2, "lock_version": gd2.get("lockVersion")}
    tr.check_ok(await session.call_tool("update_project", up2), "update", "update_project")
    tr.check_ok(await session.call_tool("delete_project", {"id": pid2}), "delete", "delete_project")
    await asyncio.sleep(0.3)
    tr.check_verdel(await session.call_tool("get_project_by_id", {"id": pid2}), "verify-delete", "get_project_by_id")

    # ────────── CATEGORIES & BUDGETS ──────────
    r = tr.check_ok(await session.call_tool("list_project_categories", {"project_id": 1}), "list categories", "list_project_categories")
    cid = get_first_id(extract_content(r))
    r = tr.check_ok(await session.call_tool("list_project_budgets", {"project_id": 1}), "list budgets", "list_project_budgets")
    bid = get_first_id(extract_content(r))
    tr.check_ok(await session.call_tool("get_category_by_id", {"id": cid}), "get category", "get_category_by_id")
    tr.check_ok(await session.call_tool("get_budget_by_id", {"id": bid}), "get budget", "get_budget_by_id")

    # ────────── VERSION ──────────
    vn = make_name("ver")
    r = tr.check_ok(await session.call_tool("create_version", {
        "name": vn, "project_id": persistent_project_id,
    }), "create", "create_version")
    vid = extract_content(r).get("id")

    tr.check_ok(await session.call_tool("list_versions", {}), "list", "list_versions")
    g = tr.check_ok(await session.call_tool("get_version_by_id", {"id": vid}), "get lock", "get_version_by_id")
    gd = extract_content(g)
    up = {"id": vid, "lock_version": gd.get("lockVersion"), "name": "upd-" + vn}
    tr.check_ok(await session.call_tool("update_version", up), "update", "update_version")
    tr.check_ok(await session.call_tool("delete_version", {"id": vid}), "delete", "delete_version")
    await asyncio.sleep(0.3)
    tr.check_verdel(await session.call_tool("get_version_by_id", {"id": vid}), "verify-delete", "get_version_by_id")

    # ────────── USER ──────────
    sun = make_name("usr")
    r = tr.check_ok(await session.call_tool("create_user", {
        "login": sun, "first_name": "Test", "last_name": "User",
        "email": f"{sun}@test.com", "password": "Passw0rd!!!", "admin": False,
    }), "create", "create_user")
    suid = extract_content(r).get("id")

    tr.check_ok(await session.call_tool("get_user_by_id", {"id": suid}), "get user", "get_user_by_id")
    g = tr.check_ok(await session.call_tool("get_user_by_id", {"id": suid}), "get lock", "get_user_by_id")
    tr.check_ok(await session.call_tool("update_user", {"id": suid, "first_name": "Updated"}), "update", "update_user")

    # ────────── GROUP + MEMBERSHIP ──────────
    gn = make_name("group")
    r = tr.check_ok(await session.call_tool("create_group", {"name": gn}), "create", "create_group")
    gid = extract_content(r).get("id")

    tr.check_ok(await session.call_tool("get_group_by_id", {"id": gid}), "get group", "get_group_by_id")
    tr.check_ok(await session.call_tool("update_group", {
        "id": gid, "name": "upd-" + gn, "member_ids": [suid],
    }), "update group", "update_group")

    mc = tr.check_ok(await session.call_tool("create_membership", {
        "project_id": persistent_project_id, "principal_id": gid, "role_ids": [role_id],
    }), "create", "create_membership")
    mid = extract_content(mc).get("id")

    tr.check_ok(await session.call_tool("list_memberships", {}), "list", "list_memberships")
    tr.check_ok(await session.call_tool("get_membership_by_id", {"id": mid}), "get", "get_membership_by_id")
    tr.check_ok(await session.call_tool("update_membership", {"id": mid, "role_ids": [role_id]}), "update", "update_membership")
    tr.check_ok(await session.call_tool("delete_membership", {"id": mid}), "delete", "delete_membership")
    await asyncio.sleep(0.3)
    tr.check_verdel(await session.call_tool("get_membership_by_id", {"id": mid}), "verify-delete", "get_membership_by_id")

    tr.check_ok(await session.call_tool("delete_group", {"id": gid}), "delete group", "delete_group")

    # ────────── WORK PACKAGE CRUD ──────────
    wn = make_name("wp")
    r = tr.check_ok(await session.call_tool("create_work_package", {
        "subject": wn, "project_id": persistent_project_id,
        "type_id": type_id, "priority_id": priority_id, "status_id": status_id,
    }), "create", "create_work_package")
    wpid = extract_content(r).get("id")

    tr.check_ok(await session.call_tool("list_work_packages", {}), "list", "list_work_packages")
    tr.check_ok(await session.call_tool("get_work_package_by_id", {"id": wpid}), "get", "get_work_package_by_id")
    tr.check_ok(await session.call_tool("add_work_package_comment", {"id": wpid, "comment": "Test comment"}), "add comment", "add_work_package_comment")

    act_r = tr.check_ok(await session.call_tool("get_work_package_activities", {"id": wpid}), "get activities", "get_work_package_activities")
    act_id = get_first_id(extract_content(act_r))

    tr.check_ok(await session.call_tool("add_work_package_watcher", {"id": wpid, "user_id": suid}), "add watcher", "add_work_package_watcher")
    tr.check_ok(await session.call_tool("get_work_package_watchers", {"id": wpid}), "get watchers", "get_work_package_watchers")
    tr.check_ok(await session.call_tool("remove_work_package_watcher", {"id": wpid, "user_id": suid}), "remove watcher", "remove_work_package_watcher")

    wp2 = tr.check_ok(await session.call_tool("create_work_package", {
        "subject": wn + "-rel", "project_id": persistent_project_id,
        "type_id": type_id, "priority_id": priority_id, "status_id": status_id,
    }), "create related wp", "create_work_package")
    wp2id = extract_content(wp2).get("id")

    tr.check_ok(await session.call_tool("create_work_package_relation", {
        "id": wpid, "target_id": wp2id, "relation_type": "relates",
    }), "create relation", "create_work_package_relation")
    tr.check_ok(await session.call_tool("get_work_package_relations", {"id": wpid}), "get relations", "get_work_package_relations")
    tr.check_ok(await session.call_tool("delete_work_package", {"id": wp2id}), "delete related wp", "delete_work_package")
    await asyncio.sleep(0.3)
    tr.check_ok(await session.call_tool("list_work_package_attachments", {"id": wpid}), "list attachments", "list_work_package_attachments")

    tr.check_ok(await session.call_tool("toggle_emoji_reaction", {
        "activity_id": act_id, "reaction": "thumbs_up",
    }), "toggle emoji", "toggle_emoji_reaction")
    tr.check_ok(await session.call_tool("list_emoji_reactions", {"activity_id": act_id}), "list emoji", "list_emoji_reactions")

    future = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    rr = tr.check_ok(await session.call_tool("create_reminder", {
        "work_package_id": wpid, "remind_at": future, "note": "Test reminder",
    }), "create reminder", "create_reminder")
    rrid = extract_content(rr).get("id")

    tr.check_ok(await session.call_tool("update_reminder", {
        "id": rrid, "note": "Updated reminder",
    }), "update reminder", "update_reminder")
    tr.check_ok(await session.call_tool("delete_reminder", {"id": rrid}), "delete reminder", "delete_reminder")
    await asyncio.sleep(0.3)
    tr.check_verdel(await session.call_tool("delete_reminder", {"id": rrid}), "verify reminder delete", "delete_reminder")

    g = tr.check_ok(await session.call_tool("get_work_package_by_id", {"id": wpid}), "get lock", "get_work_package_by_id")
    gd = extract_content(g)
    up = {"id": wpid, "subject": "upd-" + wn, "lock_version": gd.get("lockVersion")}
    tr.check_ok(await session.call_tool("update_work_package", up), "update", "update_work_package")
    tr.check_ok(await session.call_tool("delete_work_package", {"id": wpid}), "delete", "delete_work_package")
    await asyncio.sleep(0.3)
    tr.check_verdel(await session.call_tool("get_work_package_by_id", {"id": wpid}), "verify-delete", "get_work_package_by_id")

    # ────────── NOTIFICATION ──────────
    nn = make_name("notif")
    nr = tr.check_ok(await session.call_tool("create_work_package", {
        "subject": nn, "project_id": persistent_project_id,
        "type_id": type_id, "priority_id": priority_id, "status_id": status_id,
        "description": f"Hey @user#{user_id} check this",
    }), "create notif WP", "create_work_package")
    nwid = extract_content(nr).get("id")

    await asyncio.sleep(8)

    nid_r = tr.check_ok(await session.call_tool("list_notifications", {}), "list notifications", "list_notifications")
    nid = get_first_id(extract_content(nid_r))
    tr.check_ok(await session.call_tool("get_notification_by_id", {"id": nid}), "get notification", "get_notification_by_id")
    tr.check_ok(await session.call_tool("delete_work_package", {"id": nwid}), "delete notif WP", "delete_work_package")
    await asyncio.sleep(0.3)

    # ────────── DELETE USER ──────────
    tr.check_ok(await session.call_tool("delete_user", {"id": suid}), "delete user", "delete_user")
    await asyncio.sleep(0.3)
    tr.check_verdel(await session.call_tool("get_user_by_id", {"id": suid}), "verify user delete", "get_user_by_id")

    # ────────── MEETING CRUD ──────────
    mn = make_name("mtg")
    r = tr.check_ok(await session.call_tool("create_meeting", {
        "title": mn, "project_id": persistent_project_id,
        "start_time": "2026-07-01T10:00:00+00:00", "end_time": "2026-07-01T11:00:00+00:00",
    }), "create", "create_meeting")
    mtid = extract_content(r).get("id")

    tr.check_ok(await session.call_tool("list_meetings", {}), "list", "list_meetings")
    tr.check_ok(await session.call_tool("get_meeting_by_id", {"id": mtid}), "get", "get_meeting_by_id")
    tr.check_ok(await session.call_tool("list_meeting_agenda_items", {"meeting_id": mtid}), "list agenda", "list_meeting_agenda_items")
    tr.check_ok(await session.call_tool("list_meeting_sections", {"meeting_id": mtid}), "list sections", "list_meeting_sections")

    ac = tr.check_ok(await session.call_tool("create_meeting_agenda_item", {
        "meeting_id": mtid, "item_type": "simple", "title": "Ag1",
    }), "create agenda", "create_meeting_agenda_item")
    agid = extract_content(ac).get("id")

    tr.check_ok(await session.call_tool("get_meeting_agenda_item_by_id", {"meeting_id": mtid, "id": agid}), "get agenda", "get_meeting_agenda_item_by_id")
    tr.check_ok(await session.call_tool("update_meeting_agenda_item", {"meeting_id": mtid, "id": agid, "title": "UpdAg"}), "update agenda", "update_meeting_agenda_item")
    tr.check_ok(await session.call_tool("delete_meeting_agenda_item", {"meeting_id": mtid, "id": agid}), "delete agenda", "delete_meeting_agenda_item")

    sc = tr.check_ok(await session.call_tool("create_meeting_section", {
        "meeting_id": mtid, "title": "Sec1", "position": 1,
    }), "create section", "create_meeting_section")
    scid = extract_content(sc).get("id")

    tr.check_ok(await session.call_tool("get_meeting_section_by_id", {"meeting_id": mtid, "id": scid}), "get section", "get_meeting_section_by_id")
    tr.check_ok(await session.call_tool("update_meeting_section", {"meeting_id": mtid, "id": scid, "title": "UpdSec"}), "update section", "update_meeting_section")
    tr.check_ok(await session.call_tool("delete_meeting_section", {"meeting_id": mtid, "id": scid}), "delete section", "delete_meeting_section")

    tr.check_ok(await session.call_tool("update_meeting", {"id": mtid, "title": "upd-" + mn}), "update", "update_meeting")
    tr.check_ok(await session.call_tool("delete_meeting", {"id": mtid}), "delete", "delete_meeting")
    await asyncio.sleep(0.3)
    tr.check_verdel(await session.call_tool("get_meeting_by_id", {"id": mtid}), "verify-delete", "get_meeting_by_id")

    # ────────── NEWS CRUD ──────────
    nn = make_name("news")
    r = tr.check_ok(await session.call_tool("create_news", {
        "title": nn, "project_id": persistent_project_id,
    }), "create", "create_news")
    nid = extract_content(r).get("id")

    tr.check_ok(await session.call_tool("list_news", {}), "list", "list_news")
    tr.check_ok(await session.call_tool("get_news_by_id", {"id": nid}), "get", "get_news_by_id")
    tr.check_ok(await session.call_tool("update_news", {"id": nid, "title": "upd-" + nn}), "update", "update_news")
    tr.check_ok(await session.call_tool("delete_news", {"id": nid}), "delete", "delete_news")
    await asyncio.sleep(0.3)
    tr.check_verdel(await session.call_tool("get_news_by_id", {"id": nid}), "verify-delete", "get_news_by_id")

    # ────────── GRID CRUD ──────────
    gn = make_name("grid")
    scope_href = f"/projects/{persistent_project_id}/boards"
    r = tr.check_ok(await session.call_tool("create_grid", {
        "page": gn, "row_count": 3, "column_count": 2, "scope_href": scope_href,
    }), "create", "create_grid")
    gid = extract_content(r).get("id")

    tr.check_ok(await session.call_tool("list_grids", {}), "list", "list_grids")
    tr.check_ok(await session.call_tool("get_grid_by_id", {"id": gid}), "get", "get_grid_by_id")
    tr.check_ok(await session.call_tool("update_grid", {"id": gid}), "update", "update_grid")
    tr.check_ok(await session.call_tool("delete_grid", {"id": gid}), "delete", "delete_grid")
    await asyncio.sleep(0.3)
    tr.check_verdel(await session.call_tool("get_grid_by_id", {"id": gid}), "verify-delete", "get_grid_by_id")

    # ────────── TIME ENTRY CRUD ──────────
    ten = make_name("te")
    te_wp_r = tr.check_ok(await session.call_tool("create_work_package", {
        "subject": "te-" + ten, "project_id": persistent_project_id,
        "type_id": type_id, "priority_id": priority_id, "status_id": status_id,
    }), "create te wp", "create_work_package")
    te_wpid = extract_content(te_wp_r).get("id")

    te = tr.check_ok(await session.call_tool("create_time_entry", {
        "project_id": persistent_project_id, "work_package_id": te_wpid,
        "hours": "PT2H", "spent_on": "2026-06-27", "comment": ten,
    }), "create", "create_time_entry")
    teid = extract_content(te).get("id")

    tr.check_ok(await session.call_tool("get_time_entry_by_id", {"id": teid}), "get", "get_time_entry_by_id")
    tr.check_ok(await session.call_tool("update_time_entry", {"id": teid, "hours": "PT4H"}), "update", "update_time_entry")
    tr.check_ok(await session.call_tool("delete_time_entry", {"id": teid}), "delete", "delete_time_entry")
    await asyncio.sleep(0.3)
    tr.check_verdel(await session.call_tool("get_time_entry_by_id", {"id": teid}), "verify-delete", "get_time_entry_by_id")

    tr.check_ok(await session.call_tool("list_time_entries", {}), "list", "list_time_entries")

    # ────────── RECURRING MEETING CRUD ──────────
    rmn = make_name("rm")
    r = tr.check_ok(await session.call_tool("create_recurring_meeting", {
        "project_id": persistent_project_id, "title": rmn, "frequency": "weekly",
        "start_time": "2026-07-01T10:00:00+00:00", "end_time": "2026-07-01T11:00:00+00:00",
        "days": [1],
    }), "create", "create_recurring_meeting")
    rmid = extract_content(r).get("id")

    tr.check_ok(await session.call_tool("list_recurring_meetings", {}), "list", "list_recurring_meetings")
    tr.check_ok(await session.call_tool("get_recurring_meeting_by_id", {"id": rmid}), "get", "get_recurring_meeting_by_id")
    tr.check_ok(await session.call_tool("update_recurring_meeting", {"id": rmid, "title": "upd-" + rmn}), "update", "update_recurring_meeting")
    tr.check_ok(await session.call_tool("delete_recurring_meeting", {"id": rmid}), "delete", "delete_recurring_meeting")
    await asyncio.sleep(0.3)
    tr.check_verdel(await session.call_tool("get_recurring_meeting_by_id", {"id": rmid}), "verify-delete", "get_recurring_meeting_by_id")

    # ────────── CLEANUP ──────────
    tr.check_ok(await session.call_tool("delete_project", {"id": persistent_project_id}), "delete base project", "delete_project")
    await asyncio.sleep(0.3)
    tr.check_verdel(await session.call_tool("get_project_by_id", {"id": persistent_project_id}), "verify base deleted", "get_project_by_id")

    # ══════════════════════════════════════════════════════════════════
    # Phase 5: Leak Detection
    # ══════════════════════════════════════════════════════════════════
    tr.print_phase("Phase 5 — Leak Detection")

    leak_config = {
        "projects": {"list_tool": "list_projects", "del_tool": "delete_project", "match_field": "name"},
        "work_packages": {"list_tool": "list_work_packages", "del_tool": "delete_work_package", "match_field": "subject"},
        "versions": {"list_tool": "list_versions", "del_tool": "delete_version", "match_field": "name"},
        "meetings": {"list_tool": "list_meetings", "del_tool": "delete_meeting", "match_field": "title"},
        "news": {"list_tool": "list_news", "del_tool": "delete_news", "match_field": "title"},
        "grids": {"list_tool": "list_grids", "del_tool": "delete_grid", "match_field": "page"},
        "time_entries": {"list_tool": "list_time_entries", "del_tool": "delete_time_entry", "match_field": "comment"},
        "recurring_meetings": {"list_tool": "list_recurring_meetings", "del_tool": "delete_recurring_meeting", "match_field": "title"},
        "groups": {"list_tool": "list_groups", "del_tool": "delete_group", "match_field": "name"},
    }

    leak_found = False
    rid_prefix = f"t{rid}-"

    for domain, cfg in leak_config.items():
        lt = cfg["list_tool"]
        dt = cfg["del_tool"]
        mf = cfg["match_field"]
        lr = await session.call_tool(lt, {"page_size": 100})
        lc = extract_content(lr)
        for item in get_list_items(lc):
            if isinstance(item, dict):
                nv = str(item.get(mf, ""))
                if isinstance(nv, str) and nv.startswith(rid_prefix):
                    leak_found = True
                    art_id = item.get("id")
                    print(f"  LEAK DETECTED: {domain} id={art_id} {mf}='{nv}'")
                    await session.call_tool(dt, {"id": art_id})

    if leak_found:
        tr.f("Leak Detection", "leak_scan", "Test artifacts found")
    else:
        tr.p("Leak Detection", "leak_scan")

    # Report
    tr.report()
    await session.close()

    if tr.failed:
        sys.exit(1)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
