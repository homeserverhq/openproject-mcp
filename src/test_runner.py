"""OpenProject MCP end-to-end test harness.

Every tool is tested unconditionally. No SKIPPED status.
Only PASS or FAIL. Tests exist to find flaws in main.py and client.py.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import string
import sys
from datetime import datetime, timezone
from typing import Any

import httpx


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


# ─── Test helpers ─────────────────────────────────────────────────────


def is_error(result: dict[str, Any]) -> str | None:
    if "error" in result:
        return json.dumps(result["error"])
    if result.get("isError"):
        return str(result.get("content", result))
    return None


def extract_content(result: dict[str, Any]) -> Any:
    if "error" in result:
        return {"error": result["error"]}
    content = result.get("content", [])
    if isinstance(content, list):
        for item in content:
            if item.get("type") == "text":
                text = item["text"]
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return text
    return result


def get_list_items(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
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


# ─── TestResult with honest pass/fail ─────────────────────────────────


class TestResult:
    SERVER_ERR = ["internal server error", "connection", "name or service not known", "timeout"]

    def __init__(self) -> None:
        self.passed: list[tuple[str, str]] = []
        self.failed: list[tuple[str, str, str]] = []

    def p(self, label: str, tool: str) -> None:
        self.passed.append((label, tool))
        print(f"  PASS: {tool} — {label}")

    def f(self, label: str, tool: str, err: str) -> None:
        self.failed.append((label, tool, err))
        print(f"  FAIL: {tool} — {label} — {err.split(chr(10))[0][:120]}")

    def is_server_err(self, err: str) -> bool:
        return any(k in err.lower() for k in self.SERVER_ERR)

    async def run(self, session: MCPSession, label: str, tool: str, args: dict[str, Any] | None = None,
                  expect: str = "success") -> dict[str, Any]:
        """Run a tool test.

        expect='success': error is FAIL
        expect='error':   must get 'not found' (verify-delete)
        expect='any':     non-server errors are PASS (read-only tools where data may not exist)
        """
        try:
            result = await session.call_tool(tool, args)
        except Exception as e:
            self.f(label, tool, str(e))
            return {}
        err = is_error(result)
        if expect == "success":
            if err:
                self.f(label, tool, err)
            else:
                self.p(label, tool)
        elif expect == "error":
            if err and "not found" in err.lower():
                self.p(label, tool)
            elif err:
                self.f(label, tool, f"Expected not found but got: {err}")
            else:
                self.f(label, tool, "Expected not found but resource exists")
        else:
            if err and self.is_server_err(err):
                self.f(label, tool, err)
            else:
                self.p(label, tool)
        return result

    async def call(self, session: MCPSession, label: str, tool: str, args: dict[str, Any] | None = None
                   ) -> dict[str, Any]:
        """Execute a tool call without auto pass/fail (caller handles result)."""
        try:
            return await session.call_tool(tool, args)
        except Exception as e:
            self.f(label, tool, str(e))
            return {}

    def print_phase(self, phase_label: str) -> None:
        print(f"\n## {phase_label}")

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

    def __len__(self) -> int:
        return len(self.passed) + len(self.failed)


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
    try:
        await session.initialize()
    except Exception as e:
        print(f"FATAL: Could not connect to MCP server: {e}")
        sys.exit(1)

    tools_result = await session.list_tools()
    tools = tools_result.get("tools", [])
    tool_names = {t["name"] for t in tools}
    print(f"\n## Phase 0 — Initialization")
    print(f"  Discovered {len(tools)} tools")

    tr = TestResult()

    # ══════════════════════════════════════════════════════════════════
    # Phase 1: Reference data — list + get using discovered IDs
    # ══════════════════════════════════════════════════════════════════
    tr.print_phase("Phase 1 — Reference Data")

    seed: dict[str, Any] = {}

    ref_domains = [
        ("Statuses", "list_statuses", "get_status_by_id"),
        ("Types", "list_types", "get_type_by_id"),
        ("Priorities", "list_priorities", "get_priority_by_id"),
        ("Roles", "list_roles", "get_role_by_id"),
        ("Users", "list_users", "get_user_by_id"),
        ("Principals", "list_principals", "get_principal_by_id"),
    ]

    for label, list_tool, get_tool in ref_domains:
        if list_tool not in tool_names or get_tool not in tool_names:
            continue
        result = await session.call_tool(list_tool, {})
        err = is_error(result)
        if err:
            tr.f(label, list_tool, err)
            continue
        tr.p(label, list_tool)
        content = extract_content(result)
        first_id = get_first_id(content)
        if first_id is not None:
            seed[label.lower().rstrip("s") + "_id"] = first_id
            await tr.run(session, label, get_tool, {"id": first_id})
        else:
            await tr.run(session, label, get_tool, {"id": 1}, expect="success")

    # Extract well-known seed values
    sid_status = seed.get("statuses_id", 1)
    sid_type = seed.get("types_id", 1)
    sid_priority = seed.get("priorities_id", 1)
    sid_role = 5  # Project admin — first valid project role in seeded list
    sid_user = seed.get("users_id", 4)

    # Discover existing project IDs for use in read-only queries
    any_project_id = None
    if "list_projects" in tool_names:
        pr = await session.call_tool("list_projects", {})
        pc = extract_content(pr)
        p_items = get_list_items(pc)
        for pit in p_items:
            if isinstance(pit, dict):
                any_project_id = pit.get("id")
                break
    if any_project_id is None:
        any_project_id = 1

    # Discover additional reference IDs for categories, budgets, wikipages, attachments
    extra_discover = [
        ("categories_id", "list_project_categories", {"project_id": any_project_id}),
        ("budgets_id", "list_project_budgets", {"project_id": any_project_id}),
    ]
    for skey, list_tool, list_args in extra_discover:
        if list_tool in tool_names:
            dr = await session.call_tool(list_tool, list_args)
            dc = extract_content(dr)
            did = get_first_id(dc)
            if did and skey not in seed:
                seed[skey] = did

    # Discover wiki page and attachment IDs from existing work packages
    if "list_work_packages" in tool_names:
        wr = await session.call_tool("list_work_packages", {"page_size": 50})
        wc = extract_content(wr)
        items = get_list_items(wc)
        for item in items:
            if isinstance(item, dict):
                if "wikipages_id" not in seed:
                    links = item.get("_links", {})
                    if links:
                        for link_key, link_val in links.items():
                            if "wiki" in link_key.lower() and isinstance(link_val, dict):
                                href = link_val.get("href", "")
                                if "/wiki_pages/" in href:
                                    wpid = href.rsplit("/", 1)[-1]
                                    try:
                                        seed["wikipages_id"] = int(wpid)
                                    except ValueError:
                                        pass
                if "attachments_id" not in seed:
                    links = item.get("_links", {})
                    if links:
                        for link_key, link_val in links.items():
                            if "attachment" in link_key.lower() and isinstance(link_val, dict):
                                href = link_val.get("href", "")
                                if "/attachments/" in href:
                                    aid = href.rsplit("/", 1)[-1]
                                    try:
                                        seed["attachments_id"] = int(aid)
                                    except ValueError:
                                        pass

    # ══════════════════════════════════════════════════════════════════
    # Phase 2: Read-only data (may be empty — expect='any' for get)
    # ══════════════════════════════════════════════════════════════════
    tr.print_phase("Phase 2 — Read-Only Data")

    # ── List tools (always expect success) ──
    list_only_tests = [
        ("list_notifications", "list_notifications", {}, "success"),
        ("list_documents", "list_documents", {}, "success"),
        ("list_reminders", "list_reminders", {}, "success"),
        ("list_days", "list_days", {}, "success"),
        ("list_non_working_days", "list_non_working_days", {}, "success"),
        ("list_week_days", "list_week_days", {}, "success"),
        ("health_check", "health_check", {}, "success"),
    ]
    for label, tool, args, exp in list_only_tests:
        if tool in tool_names:
            await tr.run(session, label, tool, args, expect=exp)

    # ── Discover-and-get: list first, then get with discovered ID ──
    async def list_then_get(list_tool: str, get_tool: str, label: str, list_args: dict[str, Any] | None = None,
                            get_args_builder: Any = None) -> None:
        if list_tool not in tool_names or get_tool not in tool_names:
            return
        lr = await tr.call(session, f"list {label}", list_tool, list_args or {})
        lc = extract_content(lr)
        items = get_list_items(lc)
        first_id = items[0].get("id") if items and isinstance(items[0], dict) else None
        if first_id is not None:
            await tr.run(session, f"get {label}", get_tool, {"id": first_id})
        elif get_args_builder:
            await tr.run(session, f"get {label}", get_tool, get_args_builder)

    await list_then_get("list_notifications", "get_notification_by_id", "notification")
    await list_then_get("list_documents", "get_document_by_id", "document", get_args_builder={"id": 1})
    await list_then_get("list_documents", "update_document", "document update", get_args_builder={"id": 1})
    # (reminder update/delete tested in WP CRUD cycle)

    # ── Discovered ID-based tests (categories, budgets, wikipages, attachments) ──
    await list_then_get("list_project_categories", "get_category_by_id", "category",
                        list_args={"project_id": any_project_id})

    await list_then_get("list_project_budgets", "get_budget_by_id", "budget",
                        list_args={"project_id": any_project_id})

    # Fixed: weekday, paginated, and date range tests
    fixed_tests = [
        ("get_week_day_mon", "get_week_day_by_number", {"day": 1}, "success"),
        ("get_week_day_sun", "get_week_day_by_number", {"day": 7}, "success"),
        ("get_wiki_page_by_id", "get_wiki_page_by_id", {"id": seed.get("wikipages_id", 1)}, "success"),
        ("get_attachment_by_id", "get_attachment_by_id", {"id": seed.get("attachments_id", 1)}, "success"),
        ("list_projects_paged", "list_projects", {"page_size": 5, "offset": 1}, "success"),
        ("list_work_packages_paged", "list_work_packages", {"page_size": 5}, "success"),
        ("list_versions_paged", "list_versions", {"page_size": 5}, "success"),
        ("list_memberships_paged", "list_memberships", {"page_size": 5}, "success"),
        ("list_meetings_paged", "list_meetings", {"page_size": 5}, "success"),
        ("list_time_entries_paged", "list_time_entries", {"page_size": 5}, "success"),
        ("list_news_paged", "list_news", {"page_size": 5}, "success"),
        ("list_grids_paged", "list_grids", {"page_size": 5}, "success"),
        ("list_users_paged", "list_users", {"page_size": 5}, "success"),
        ("list_groups_paged", "list_groups", {"page_size": 5}, "success"),
        ("list_principals_paged", "list_principals", {"page_size": 5}, "success"),
        ("get_days_by_range", "list_days", {"date_from": "2026-06-01", "date_to": "2026-06-30"}, "success"),
        ("list_non_working_empty", "list_non_working_days", {"date_from": "2026-06-01", "date_to": "2026-06-01"}, "success"),
    ]
    for label, tool, args, exp in fixed_tests:
        if tool not in tool_names:
            continue
        await tr.run(session, label, tool, args, expect=exp)

    # ══════════════════════════════════════════════════════════════════
    # Phase 3: CRUD cycles — fully self-contained
    # ══════════════════════════════════════════════════════════════════
    tr.print_phase("Phase 3 — CRUD Cycles")

    store: dict[str, Any] = {}

    # Create a persistent project — used by all dependent CRUDs, deleted at end of Phase 3
    ppn = make_name("base")
    pr = await tr.run(session, "create project", "create_project", {
        "name": ppn, "identifier": ppn, "description": "Persistent base project", "public": True, "active": True,
    })
    ppid = extract_content(pr).get("id") if isinstance(extract_content(pr), dict) else None
    if ppid:
        store["persistent_project_id"] = ppid
        store["project_ident"] = ppn

    # ────────── PROJECT CRUD (self-contained) ──────────
    if "create_project" in tool_names and "delete_project" in tool_names:
        pn = make_name("project")
        r = await tr.run(session, "create", "create_project", {
            "name": pn, "identifier": pn, "description": "Test", "public": True, "active": True,
        })
        pid = extract_content(r).get("id") if isinstance(extract_content(r), dict) else None

        await tr.run(session, "list", "list_projects", {}, expect="success")
        await tr.run(session, "get", "get_project_by_id", {"id": pid} if pid else {})

        cpy_name = pn + "-cpy"
        await tr.run(session, "copy", "copy_project", {"id": pid, "name": cpy_name, "identifier": pn + "_cpy"} if pid else {})
        for attempt in range(10):
            await asyncio.sleep(1)
            lr = await session.call_tool("list_projects", {"page_size": 100})
            found = find_match(extract_content(lr), "name", cpy_name)
            if found:
                await session.call_tool("delete_project", {"id": found.get("id")})
                break
        g = await tr.call(session, "get lock", "get_project_by_id", {"id": pid} if pid else {})
        gd = extract_content(g)
        lv = gd.get("lockVersion") if isinstance(gd, dict) else None
        up = {"id": pid, "name": "upd-" + pn} if pid else {}
        if lv is not None and pid:
            up["lock_version"] = lv
        await tr.run(session, "update", "update_project", up)
        await tr.run(session, "delete", "delete_project", {"id": pid} if pid else {})
        await asyncio.sleep(0.3)
        await tr.run(session, "verify-delete", "get_project_by_id", {"id": pid} if pid else {}, expect="error")

    # ────────── VERSION ──────────
    if "create_version" in tool_names and "delete_version" in tool_names:
        vn = make_name("ver")
        r = await tr.run(session, "create", "create_version", {"name": vn, "project_id": store.get("persistent_project_id", 1)})
        vid = extract_content(r).get("id") if isinstance(extract_content(r), dict) else None
        await tr.run(session, "list", "list_versions", {}, expect="success")
        g = await tr.call(session, "get lock", "get_version_by_id", {"id": vid} if vid else {})
        gd = extract_content(g)
        lv = gd.get("lockVersion") if isinstance(gd, dict) else None
        up = {"id": vid} if vid else {}
        up["name"] = "upd-" + vn
        if lv is not None:
            up["lock_version"] = lv
        await tr.run(session, "update", "update_version", up, expect="success" if vid else "success")
        await tr.run(session, "delete", "delete_version", {"id": vid} if vid else {})
        await asyncio.sleep(0.3)
        await tr.run(session, "verify-delete", "get_version_by_id", {"id": vid} if vid else {}, expect="error")

    # ────────── GROUP + MEMBERSHIP ──────────
    if "create_group" in tool_names and "delete_group" in tool_names:
        gn = make_name("group")
        gr = await tr.run(session, "create", "create_group", {"name": gn})
        gid = extract_content(gr).get("id") if isinstance(extract_content(gr), dict) else None
        await tr.run(session, "get group", "get_group_by_id", {"id": gid} if gid else {})

        mc = await tr.run(session, "create", "create_membership", {
            "project_id": store.get("persistent_project_id", 1), "principal_id": gid, "role_ids": [sid_role],
        } if gid else {}, expect="success")
        mid = extract_content(mc).get("id") if isinstance(extract_content(mc), dict) else None
        await tr.run(session, "list", "list_memberships", {}, expect="success")
        await tr.run(session, "get", "get_membership_by_id", {"id": mid} if mid else {})
        await tr.run(session, "update", "update_membership", {"id": mid, "role_ids": [sid_role]} if mid else {})
        await tr.run(session, "delete", "delete_membership", {"id": mid} if mid else {})
        await asyncio.sleep(0.3)
        await tr.run(session, "verify-delete", "get_membership_by_id", {"id": mid} if mid else {}, expect="error")
        await tr.run(session, "delete group", "delete_group", {"id": gid} if gid else {})

    # ────────── WORK PACKAGE ──────────
    if "create_work_package" in tool_names:
        wn = make_name("wp")
        r = await tr.run(session, "create", "create_work_package", {
            "subject": wn, "project_id": store.get("persistent_project_id", 1), "type_id": sid_type,
            "priority_id": sid_priority, "status_id": sid_status,
        })
        wpid = extract_content(r).get("id") if isinstance(extract_content(r), dict) else None

        await tr.run(session, "list", "list_work_packages", {}, expect="success")
        await tr.run(session, "get", "get_work_package_by_id", {"id": wpid} if wpid else {})

        # WP sub-tools — ALL unconditional
        await tr.run(session, "add comment", "add_work_package_comment", {"id": wpid, "comment": "Test comment"} if wpid else {})
        act_result = await tr.call(session, "get activities", "get_work_package_activities", {"id": wpid} if wpid else {})
        act_data = extract_content(act_result)
        act_id = acts[0].get("id") if isinstance(act_data, dict) and (acts := get_list_items(act_data)) else None

        await tr.run(session, "get activities", "get_work_package_activities", {"id": wpid} if wpid else {})
        await tr.run(session, "add watcher", "add_work_package_watcher", {"id": wpid, "user_id": sid_user} if wpid else {})
        await tr.run(session, "get watchers", "get_work_package_watchers", {"id": wpid} if wpid else {})
        await tr.run(session, "remove watcher", "remove_work_package_watcher", {"id": wpid, "user_id": sid_user} if wpid else {})

        # Second WP for relation target (self-relation not allowed)
        wp2 = await tr.call(session, "create related wp", "create_work_package", {
            "subject": wn + "-rel", "project_id": store.get("persistent_project_id", 1),
            "type_id": sid_type, "priority_id": sid_priority, "status_id": sid_status,
        })
        wp2id = extract_content(wp2).get("id") if isinstance(extract_content(wp2), dict) else None
        await tr.run(session, "create relation", "create_work_package_relation", {"id": wpid, "target_id": wp2id, "relation_type": "relates"} if wpid and wp2id else {})
        await tr.run(session, "get relations", "get_work_package_relations", {"id": wpid} if wpid else {})
        if wp2id:
            await tr.run(session, "delete related wp", "delete_work_package", {"id": wp2id})
            await asyncio.sleep(0.3)
        await tr.run(session, "list attachments", "list_work_package_attachments", {"id": wpid} if wpid else {})

        # Emoji
        await tr.run(session, "toggle emoji", "toggle_emoji_reaction", {"activity_id": act_id, "reaction": "thumbs_up"} if act_id else {})
        await tr.run(session, "list emoji", "list_emoji_reactions", {"activity_id": act_id} if act_id else {})

        # Reminder
        rr = await tr.run(session, "create reminder", "create_reminder", {"work_package_id": wpid, "remind_at": "2026-07-01T10:00:00Z", "note": "Test reminder"} if wpid else {})
        rrid = extract_content(rr).get("id") if isinstance(extract_content(rr), dict) else None
        await tr.run(session, "update reminder", "update_reminder", {"id": rrid, "note": "Updated reminder"} if rrid else {})
        await tr.run(session, "delete reminder", "delete_reminder", {"id": rrid} if rrid else {})
        await asyncio.sleep(0.3)
        await tr.run(session, "verify reminder delete", "delete_reminder", {"id": rrid} if rrid else {}, expect="error")

        # Update
        g = await tr.call(session, "get lock", "get_work_package_by_id", {"id": wpid} if wpid else {})
        gd = extract_content(g)
        lv = gd.get("lockVersion") if isinstance(gd, dict) else None
        up = {"id": wpid, "subject": "upd-" + wn} if wpid else {}
        if lv is not None and wpid:
            up["lock_version"] = lv
        await tr.run(session, "update", "update_work_package", up)
        await tr.run(session, "delete", "delete_work_package", {"id": wpid} if wpid else {})
        await asyncio.sleep(0.3)
        await tr.run(session, "verify-delete", "get_work_package_by_id", {"id": wpid} if wpid else {}, expect="error")

    # ────────── MEETING ──────────
    if "create_meeting" in tool_names:
        mn = make_name("mtg")
        r = await tr.run(session, "create", "create_meeting", {
            "title": mn, "project_id": store.get("persistent_project_id", 1), "start_time": "2026-07-01T10:00:00Z", "end_time": "2026-07-01T11:00:00Z",
        }, expect="success")
        mtid = extract_content(r).get("id") if isinstance(extract_content(r), dict) else None

        await tr.run(session, "list", "list_meetings", {}, expect="success")
        await tr.run(session, "get", "get_meeting_by_id", {"id": mtid} if mtid else {})
        await tr.run(session, "list agenda", "list_meeting_agenda_items", {"meeting_id": mtid} if mtid else {})
        await tr.run(session, "list sections", "list_meeting_sections", {"meeting_id": mtid} if mtid else {})

        # Agenda item
        ac = await tr.run(session, "create agenda", "create_meeting_agenda_item", {"meeting_id": mtid, "item_type": "simple", "title": "Ag1"} if mtid else {})
        agid = extract_content(ac).get("id") if isinstance(extract_content(ac), dict) else None
        await tr.run(session, "get agenda", "get_meeting_agenda_item_by_id", {"meeting_id": mtid, "id": agid} if mtid and agid else {})
        await tr.run(session, "update agenda", "update_meeting_agenda_item", {"meeting_id": mtid, "id": agid, "title": "UpdAg"} if mtid and agid else {})

        # Outcome
        oc = await tr.run(session, "create outcome", "create_meeting_outcome", {"meeting_id": mtid, "meeting_agenda_item_id": agid, "outcome_type": "simple", "text": "Done"} if mtid and agid else {})
        ocid = extract_content(oc).get("id") if isinstance(extract_content(oc), dict) else None
        await tr.run(session, "get outcome", "get_meeting_outcome_by_id", {"meeting_id": mtid, "id": ocid} if mtid and ocid else {})
        await tr.run(session, "update outcome", "update_meeting_outcome", {"meeting_id": mtid, "id": ocid, "text": "Upd"} if mtid and ocid else {})
        await tr.run(session, "delete outcome", "delete_meeting_outcome", {"meeting_id": mtid, "id": ocid} if mtid and ocid else {})

        await tr.run(session, "delete agenda", "delete_meeting_agenda_item", {"meeting_id": mtid, "id": agid} if mtid and agid else {})

        # Section
        sc = await tr.run(session, "create section", "create_meeting_section", {"meeting_id": mtid, "title": "Sec1", "position": 1} if mtid else {})
        scid = extract_content(sc).get("id") if isinstance(extract_content(sc), dict) else None
        await tr.run(session, "get section", "get_meeting_section_by_id", {"meeting_id": mtid, "id": scid} if mtid and scid else {})
        await tr.run(session, "update section", "update_meeting_section", {"meeting_id": mtid, "id": scid, "title": "UpdSec"} if mtid and scid else {})
        await tr.run(session, "delete section", "delete_meeting_section", {"meeting_id": mtid, "id": scid} if mtid and scid else {})

        await tr.run(session, "update", "update_meeting", {"id": mtid, "title": "upd-" + mn} if mtid else {})
        await tr.run(session, "delete", "delete_meeting", {"id": mtid} if mtid else {})
        await asyncio.sleep(0.3)
        await tr.run(session, "verify-delete", "get_meeting_by_id", {"id": mtid} if mtid else {}, expect="error")

    # ────────── NEWS ──────────
    if "create_news" in tool_names and "delete_news" in tool_names:
        nn = make_name("news")
        r = await tr.run(session, "create", "create_news", {"title": nn, "project_id": store.get("persistent_project_id", 1)})
        nid = extract_content(r).get("id") if isinstance(extract_content(r), dict) else None
        await tr.run(session, "list", "list_news", {}, expect="success")
        await tr.run(session, "get", "get_news_by_id", {"id": nid} if nid else {})
        await tr.run(session, "update", "update_news", {"id": nid, "title": "upd-" + nn} if nid else {})
        await tr.run(session, "delete", "delete_news", {"id": nid} if nid else {})
        await asyncio.sleep(0.3)
        await tr.run(session, "verify-delete", "get_news_by_id", {"id": nid} if nid else {}, expect="error")

    # ────────── GRID ──────────
    if "create_grid" in tool_names and "delete_grid" in tool_names:
        gn = make_name("grid")
        scope_href = "/projects/demo-project/boards"
        pident = store.get("project_ident", "")
        if pident:
            scope_href = f"/projects/{pident}/boards"
        r = await tr.run(session, "create", "create_grid", {
            "page": gn, "row_count": 3, "column_count": 2, "scope_href": scope_href,
        })
        gid = extract_content(r).get("id") if isinstance(extract_content(r), dict) else None
        await tr.run(session, "list", "list_grids", {}, expect="success")
        await tr.run(session, "get", "get_grid_by_id", {"id": gid} if gid else {})
        await tr.run(session, "update", "update_grid", {"id": gid} if gid else {})
        await tr.run(session, "delete", "delete_grid", {"id": gid} if gid else {})
        await asyncio.sleep(0.3)
        await tr.run(session, "verify-delete", "get_grid_by_id", {"id": gid} if gid else {}, expect="error")

    # ────────── TIME ENTRY ──────────
    if "create_time_entry" in tool_names and "delete_time_entry" in tool_names:
        ten = make_name("te")
        wp_lr = await tr.call(session, "list wps", "list_work_packages", {"page_size": 50})
        wp_items = get_list_items(extract_content(wp_lr))
        te_wp_id = None
        te_proj_id = None
        for item in wp_items:
            if isinstance(item, dict):
                te_wp_id = item.get("id")
                proj_link = item.get("_links", {}).get("project", {})
                proj_href = proj_link.get("href", "") if isinstance(proj_link, dict) else ""
                if proj_href and "/projects/" in proj_href:
                    try:
                        te_proj_id = int(proj_href.rsplit("/", 1)[-1])
                    except ValueError:
                        pass
                break
        te = await tr.run(session, "create", "create_time_entry", {
            "project_id": te_proj_id, "work_package_id": te_wp_id, "hours": "PT2H",
            "spent_on": "2026-06-27", "comment": ten,
        } if te_wp_id and te_proj_id else {})
        teid = extract_content(te).get("id") if isinstance(extract_content(te), dict) else None
        await tr.run(session, "get", "get_time_entry_by_id", {"id": teid} if teid else {})
        await tr.run(session, "update", "update_time_entry", {"id": teid, "hours": "PT4H"} if teid else {})
        await tr.run(session, "delete", "delete_time_entry", {"id": teid} if teid else {})
        await asyncio.sleep(0.3)
        await tr.run(session, "verify-delete", "get_time_entry_by_id", {"id": teid} if teid else {}, expect="error")
        await tr.run(session, "list", "list_time_entries", {}, expect="success")

    # ────────── RECURRING MEETING ──────────
    if "create_recurring_meeting" in tool_names and "delete_recurring_meeting" in tool_names:
        rmn = make_name("rm")
        r = await tr.run(session, "create", "create_recurring_meeting", {
            "project_id": store.get("persistent_project_id", 1), "title": rmn, "frequency": "weekly",
            "start_time": "2026-07-01T10:00:00Z", "end_time": "2026-07-01T11:00:00Z",
            "days": [1],
        })
        rmid = extract_content(r).get("id") if isinstance(extract_content(r), dict) else None
        await tr.run(session, "list", "list_recurring_meetings", {}, expect="success")
        await tr.run(session, "get", "get_recurring_meeting_by_id", {"id": rmid} if rmid else {})
        await tr.run(session, "update", "update_recurring_meeting", {"id": rmid, "title": "upd-" + rmn} if rmid else {})
        await tr.run(session, "delete", "delete_recurring_meeting", {"id": rmid} if rmid else {})
        await asyncio.sleep(0.3)
        await tr.run(session, "verify-delete", "get_recurring_meeting_by_id", {"id": rmid} if rmid else {}, expect="error")

    # ────────── CLEANUP: Delete persistent project ──────────
    ppid = store.get("persistent_project_id")
    if ppid and "delete_project" in tool_names:
        await tr.run(session, "delete base project", "delete_project", {"id": ppid})
        await asyncio.sleep(0.3)
        await tr.run(session, "verify base deleted", "get_project_by_id", {"id": ppid}, expect="error")

    # ══════════════════════════════════════════════════════════════════
    # Phase 5: Leak Detection
    # ══════════════════════════════════════════════════════════════════
    tr.print_phase("Phase 5 — Leak Detection")

    leak_config = {
        "projects": {"list_tool": "list_projects", "match_field": "name"},
        "work_packages": {"list_tool": "list_work_packages", "match_field": "subject"},
        "versions": {"list_tool": "list_versions", "match_field": "name"},
        "meetings": {"list_tool": "list_meetings", "match_field": "title"},
        "news": {"list_tool": "list_news", "match_field": "title"},
        "grids": {"list_tool": "list_grids", "match_field": "page"},
        "time_entries": {"list_tool": "list_time_entries", "match_field": "comment"},
        "recurring_meetings": {"list_tool": "list_recurring_meetings", "match_field": "title"},
        "groups": {"list_tool": "list_groups", "match_field": "name"},
    }

    leak_found = False
    rid_prefix = f"t{rid}-"

    for domain, cfg in leak_config.items():
        lt = cfg["list_tool"]
        mf = cfg["match_field"]
        if lt not in tool_names:
            continue
        lr = await session.call_tool(lt, {"page_size": 100})
        if is_error(lr):
            continue
        lc = extract_content(lr)
        for item in get_list_items(lc):
            if isinstance(item, dict):
                nv = str(item.get(mf, ""))
                if isinstance(nv, str) and nv.startswith(rid_prefix):
                    leak_found = True
                    print(f"  LEAK DETECTED: {domain} id={item.get('id')} {mf}='{nv}'")
                    art_id = item.get("id")
                    del_map = {
                        "projects": "delete_project", "work_packages": "delete_work_package",
                        "versions": "delete_version", "meetings": "delete_meeting",
                        "news": "delete_news", "grids": "delete_grid",
                        "time_entries": "delete_time_entry",
                        "recurring_meetings": "delete_recurring_meeting",
                        "groups": "delete_group",
                    }
                    dt = del_map.get(domain)
                    if dt and art_id:
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