"""OpenProject MCP end-to-end test harness.

Every tool is tested unconditionally. No SKIPPED status.
Only PASS or FAIL. Tests exist to find flaws in main.py and client.py.
"""

from __future__ import annotations

import asyncio
import json

from toon_mcp import toon_to_json
import os
import random
import string
import sys
from datetime import datetime, timedelta, timezone
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


TOON_WRAP_KEYS = ("items", "results", "rows", "tree")


def _decode_toon_val(val: Any) -> Any:
    """Decode a TOON-encoded string or pass through raw lists."""
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
    store: dict[str, Any] = {}

    _SINGULAR = {
        "Statuses": "status", "Types": "type", "Priorities": "priority",
        "Roles": "role", "Users": "user", "Principals": "principal",
    }

    ref_domains = [
        ("Statuses", "list_statuses", "get_status_by_id"),
        ("Types", "list_types", "get_type_by_id"),
        ("Priorities", "list_priorities", "get_priority_by_id"),
        ("Roles", "list_roles", "get_role_by_id"),
        ("Users", "list_users", "get_user_by_id"),
        ("Principals", "list_principals", "get_principal_by_id"),
    ]

    for label, list_tool, get_tool in ref_domains:
        result = await session.call_tool(list_tool, {})
        err = is_error(result)
        if err:
            tr.f(label, list_tool, err)
            continue
        tr.p(label, list_tool)
        content = extract_content(result)
        first_id = get_first_id(content)
        seed[_SINGULAR[label] + "_id"] = first_id
        await tr.run(session, label, get_tool, {"id": first_id})

    # Well-known reference data IDs
    sid_status = seed.get("status_id")
    sid_type = seed.get("type_id")
    sid_priority = seed.get("priority_id")
    sid_user = seed.get("user_id")

    # Discover a project role for membership tests
    sid_role = None
    rr = await session.call_tool("list_roles", {"page_size": 50})
    rc = extract_content(rr)
    for role_item in get_list_items(rc):
        if isinstance(role_item, dict):
            rname = str(role_item.get("name", "")).lower()
            if rname in ("member", "project admin", "reader"):
                sid_role = role_item.get("id")
                break

    # Create persistent project — used by ALL subsequent tests, deleted at end
    ppn = make_name("base")
    pp_result = await tr.run(session, "create base project", "create_project", {
        "name": ppn, "identifier": ppn, "description": "Persistent base project", "public": True, "active": True,
    })
    pp_content = extract_content(pp_result)
    ppid = pp_content.get("id") if isinstance(pp_content, dict) else None
    store["persistent_project_id"] = ppid
    store["project_ident"] = ppn if ppid else None

    # Sequential probe for wiki page IDs (try 1-5, no list endpoint exists)
    for wid in range(1, 6):
        wr = await session.call_tool("get_wiki_page_by_id", {"id": wid})
        if not is_error(wr):
            seed["wikipages_id"] = wid
            break

    # Sequential probe for attachment IDs (try 1-5, no list endpoint exists)
    for aid in range(1, 6):
        ar = await session.call_tool("get_attachment_by_id", {"id": aid})
        if not is_error(ar):
            seed["attachments_id"] = aid
            break

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
        await tr.run(session, label, tool, args, expect=exp)

    # ── Get tools using discovered IDs from list results ──
    async def _get_id(label: str, list_tool: str, list_args: dict[str, Any] | None = None) -> int | None:
        lr = await session.call_tool(list_tool, list_args or {})
        lc = extract_content(lr)
        items = get_list_items(lc)
        if items and isinstance(items[0], dict):
            return items[0].get("id")
        return None

    doc_id = await _get_id("documents", "list_documents")
    await tr.run(session, "get document", "get_document_by_id", {"id": doc_id})
    await tr.run(session, "update document", "update_document", {"id": doc_id})

    # Discover a non-working day date and test get_non_working_day_by_date
    nwd_date = None
    nwd_r = await session.call_tool("list_non_working_days", {"page_size": 20})
    nwd_c = extract_content(nwd_r)
    nwd_items = get_list_items(nwd_c)
    if nwd_items and isinstance(nwd_items[0], dict):
        nwd_date = nwd_items[0].get("date")
    await tr.run(session, "get non-working day", "get_non_working_day_by_date", {"date": nwd_date})

    # Fixed: weekday, paginated, and date range tests
    fixed_tests = [
        ("get_week_day_mon", "get_week_day_by_number", {"day": 1}, "success"),
        ("get_week_day_sun", "get_week_day_by_number", {"day": 7}, "success"),
        ("get_wiki_page_by_id", "get_wiki_page_by_id", {"id": seed.get("wikipages_id")}, "success"),
        ("get_attachment_by_id", "get_attachment_by_id", {"id": seed.get("attachments_id")}, "success"),
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
        await tr.run(session, label, tool, args, expect=exp)

    # ══════════════════════════════════════════════════════════════════
    # Phase 3: CRUD cycles — fully self-contained
    # ══════════════════════════════════════════════════════════════════
    tr.print_phase("Phase 3 — CRUD Cycles")

    # ────────── PROJECT CRUD ──────────
    pn = make_name("project")
    r = await tr.run(session, "create", "create_project", {
        "name": pn, "identifier": pn, "description": "Test", "public": True, "active": True,
    })
    pid = extract_content(r).get("id") if isinstance(extract_content(r), dict) else None

    await tr.run(session, "list", "list_projects", {}, expect="success")
    await tr.run(session, "get", "get_project_by_id", {"id": pid})

    # ── Copy test (independent, separate project) ──
    cpy_name = pn + "-cpy"
    cr = await tr.run(session, "copy", "copy_project", {"id": pid, "name": cpy_name, "identifier": pn + "_cpy"})
    cpy_data = extract_content(cr)
    job_id = cpy_data.get("jobId") if isinstance(cpy_data, dict) else None
    for _ in range(30):
        await asyncio.sleep(1)
        jr = await session.call_tool("get_job_status", {"job_id": job_id})
        jd = extract_content(jr)
        if isinstance(jd, dict) and jd.get("status") == "success":
            break
    cpy_found = None
    for _ in range(10):
        await asyncio.sleep(1)
        lr = await session.call_tool("list_projects", {"page_size": 100})
        cpy_found = find_match(extract_content(lr), "name", cpy_name)
        if cpy_found:
            break
    if cpy_found:
        await tr.run(session, "get copy", "get_project_by_id", {"id": cpy_found.get("id")})
        await tr.run(session, "delete copy", "delete_project", {"id": cpy_found.get("id")})
        await asyncio.sleep(0.3)
    await tr.run(session, "delete", "delete_project", {"id": pid})
    await asyncio.sleep(0.3)
    await tr.run(session, "verify-delete", "get_project_by_id", {"id": pid}, expect="error")

    # ── Update test (independent, separate project) ──
    pn2 = make_name("upd")
    r2 = await tr.run(session, "create upd project", "create_project", {
        "name": pn2, "identifier": pn2, "description": "Update test", "public": True, "active": True,
    })
    pid2 = extract_content(r2).get("id") if isinstance(extract_content(r2), dict) else None
    g2 = await tr.call(session, "get lock", "get_project_by_id", {"id": pid2})
    gd2 = extract_content(g2)
    lv2 = gd2.get("lockVersion") if isinstance(gd2, dict) else None
    up2 = {"id": pid2, "name": "upd-" + pn2, "lock_version": lv2}
    await tr.run(session, "update", "update_project", up2)
    await tr.run(session, "delete", "delete_project", {"id": pid2})
    await asyncio.sleep(0.3)
    await tr.run(session, "verify-delete", "get_project_by_id", {"id": pid2}, expect="error")

    # ────────── CATEGORIES & BUDGETS (scan up to 10 projects) ──────────
    cid = None
    bid = None
    plr = await session.call_tool("list_projects", {"page_size": 10})
    plc = extract_content(plr)
    for proj in get_list_items(plc):
        if not isinstance(proj, dict):
            continue
        pid_num = proj.get("id")
        if not pid_num:
            continue
        if cid is None:
            cid = await _get_id("category", "list_project_categories", {"project_id": pid_num})
        if bid is None:
            bid = await _get_id("budget", "list_project_budgets", {"project_id": pid_num})
        if cid is not None and bid is not None:
            break
    await tr.run(session, "get category", "get_category_by_id", {"id": cid})
    await tr.run(session, "get budget", "get_budget_by_id", {"id": bid})

    # ────────── VERSION ──────────
    vn = make_name("ver")
    r = await tr.run(session, "create", "create_version", {"name": vn, "project_id": store.get("persistent_project_id")})
    vid = extract_content(r).get("id") if isinstance(extract_content(r), dict) else None
    await tr.run(session, "list", "list_versions", {}, expect="success")
    g = await tr.call(session, "get lock", "get_version_by_id", {"id": vid})
    gd = extract_content(g)
    lv = gd.get("lockVersion") if isinstance(gd, dict) else None
    up = {"id": vid, "lock_version": lv}
    up["name"] = "upd-" + vn
    await tr.run(session, "update", "update_version", up)
    await tr.run(session, "delete", "delete_version", {"id": vid})
    await asyncio.sleep(0.3)
    await tr.run(session, "verify-delete", "get_version_by_id", {"id": vid}, expect="error")

    # ────────── USER ──────────
    suid = None
    sun = make_name("usr")
    sr = await tr.run(session, "create", "create_user", {"login": sun, "first_name": "Test", "last_name": "User", "email": f"{sun}@test.com", "password": "Passw0rd!!!", "admin": False})
    suid = extract_content(sr).get("id") if isinstance(extract_content(sr), dict) else None
    await tr.run(session, "get user", "get_user_by_id", {"id": suid})
    sr2 = await tr.call(session, "get lock", "get_user_by_id", {"id": suid})
    srd = extract_content(sr2)
    lv = srd.get("lockVersion") if isinstance(srd, dict) else None
    up = {"id": suid, "first_name": "Updated"}
    await tr.run(session, "update", "update_user", up)

    # ────────── GROUP + MEMBERSHIP ──────────
    gn = make_name("group")
    gr = await tr.run(session, "create", "create_group", {"name": gn})
    gid = extract_content(gr).get("id") if isinstance(extract_content(gr), dict) else None
    await tr.run(session, "get group", "get_group_by_id", {"id": gid})
    mid_args = {"member_ids": [suid]}
    upd_args = {"id": gid, "name": "upd-" + gn}
    if suid and gid:
        upd_args["member_ids"] = [suid]
    await tr.run(session, "update group", "update_group", upd_args)

    mc = await tr.run(session, "create", "create_membership", {
        "project_id": store.get("persistent_project_id"), "principal_id": gid, "role_ids": [sid_role],
    }, expect="success")
    mid = extract_content(mc).get("id") if isinstance(extract_content(mc), dict) else None
    await tr.run(session, "list", "list_memberships", {}, expect="success")
    await tr.run(session, "get", "get_membership_by_id", {"id": mid})
    await tr.run(session, "update", "update_membership", {"id": mid, "role_ids": [sid_role]})
    await tr.run(session, "delete", "delete_membership", {"id": mid})
    await asyncio.sleep(0.3)
    await tr.run(session, "verify-delete", "get_membership_by_id", {"id": mid}, expect="error")
    await tr.run(session, "delete group", "delete_group", {"id": gid})

    # ────────── WORK PACKAGE ──────────
    wn = make_name("wp")
    r = await tr.run(session, "create", "create_work_package", {
        "subject": wn, "project_id": store.get("persistent_project_id"), "type_id": sid_type,
        "priority_id": sid_priority, "status_id": sid_status,
    })
    wpid = extract_content(r).get("id") if isinstance(extract_content(r), dict) else None

    await tr.run(session, "list", "list_work_packages", {}, expect="success")
    await tr.run(session, "get", "get_work_package_by_id", {"id": wpid})

    await tr.run(session, "add comment", "add_work_package_comment", {"id": wpid, "comment": "Test comment"})
    act_result = await tr.call(session, "get activities", "get_work_package_activities", {"id": wpid})
    act_data = extract_content(act_result)
    act_id = acts[0].get("id") if isinstance(act_data, dict) and (acts := get_list_items(act_data)) else None

    await tr.run(session, "get activities", "get_work_package_activities", {"id": wpid})
    await tr.run(session, "add watcher", "add_work_package_watcher", {"id": wpid, "user_id": suid})
    await tr.run(session, "get watchers", "get_work_package_watchers", {"id": wpid})
    await tr.run(session, "remove watcher", "remove_work_package_watcher", {"id": wpid, "user_id": suid})

    wp2 = await tr.call(session, "create related wp", "create_work_package", {
        "subject": wn + "-rel", "project_id": store.get("persistent_project_id"),
        "type_id": sid_type, "priority_id": sid_priority, "status_id": sid_status,
    })
    wp2id = extract_content(wp2).get("id") if isinstance(extract_content(wp2), dict) else None
    await tr.run(session, "create relation", "create_work_package_relation", {"id": wpid, "target_id": wp2id, "relation_type": "relates"})
    await tr.run(session, "get relations", "get_work_package_relations", {"id": wpid})
    await tr.run(session, "delete related wp", "delete_work_package", {"id": wp2id} if wp2id else {})
    await asyncio.sleep(0.3)
    await tr.run(session, "list attachments", "list_work_package_attachments", {"id": wpid})

    await tr.run(session, "toggle emoji", "toggle_emoji_reaction", {"activity_id": act_id, "reaction": "thumbs_up"})
    await tr.run(session, "list emoji", "list_emoji_reactions", {"activity_id": act_id})

    future = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    rr = await tr.run(session, "create reminder", "create_reminder", {"work_package_id": wpid, "remind_at": future, "note": "Test reminder"})
    rrid = extract_content(rr).get("id") if isinstance(extract_content(rr), dict) else None
    await tr.run(session, "update reminder", "update_reminder", {"id": rrid, "note": "Updated reminder"})
    await tr.run(session, "delete reminder", "delete_reminder", {"id": rrid})
    await asyncio.sleep(0.3)
    await tr.run(session, "verify reminder delete", "delete_reminder", {"id": rrid}, expect="error")

    g = await tr.call(session, "get lock", "get_work_package_by_id", {"id": wpid})
    gd = extract_content(g)
    lv = gd.get("lockVersion") if isinstance(gd, dict) else None
    up = {"id": wpid, "subject": "upd-" + wn, "lock_version": lv}
    await tr.run(session, "update", "update_work_package", up)
    await tr.run(session, "delete", "delete_work_package", {"id": wpid})
    await asyncio.sleep(0.3)
    await tr.run(session, "verify-delete", "get_work_package_by_id", {"id": wpid}, expect="error")

    # Generate notification then test get_notification_by_id
    nn = make_name("notif")
    nr = await tr.run(session, "create notif WP", "create_work_package", {
        "subject": nn, "project_id": store.get("persistent_project_id"),
        "type_id": sid_type, "priority_id": sid_priority, "status_id": sid_status,
        "description": f"Hey @user#{sid_user} check this",
    })
    nwid = extract_content(nr).get("id") if isinstance(extract_content(nr), dict) else None
    await asyncio.sleep(8)
    nid = await _get_id("notification", "list_notifications")
    await tr.run(session, "get notification", "get_notification_by_id", {"id": nid})
    await tr.run(session, "delete notif WP", "delete_work_package", {"id": nwid})
    await asyncio.sleep(0.3)

    # Delete test user
    await tr.run(session, "delete user", "delete_user", {"id": suid})
    await asyncio.sleep(0.3)
    await tr.run(session, "verify user delete", "get_user_by_id", {"id": suid}, expect="error")

    # ────────── MEETING ──────────
    mn = make_name("mtg")
    r = await tr.run(session, "create", "create_meeting", {
        "title": mn, "project_id": store.get("persistent_project_id"), "start_time": "2026-07-01T10:00:00+00:00", "end_time": "2026-07-01T11:00:00+00:00",
    }, expect="success")
    mtid = extract_content(r).get("id") if isinstance(extract_content(r), dict) else None

    await tr.run(session, "list", "list_meetings", {}, expect="success")
    await tr.run(session, "get", "get_meeting_by_id", {"id": mtid})
    await tr.run(session, "list agenda", "list_meeting_agenda_items", {"meeting_id": mtid})
    await tr.run(session, "list sections", "list_meeting_sections", {"meeting_id": mtid})

    ac = await tr.run(session, "create agenda", "create_meeting_agenda_item", {"meeting_id": mtid, "item_type": "simple", "title": "Ag1"})
    agid = extract_content(ac).get("id") if isinstance(extract_content(ac), dict) else None
    await tr.run(session, "get agenda", "get_meeting_agenda_item_by_id", {"meeting_id": mtid, "id": agid})
    await tr.run(session, "update agenda", "update_meeting_agenda_item", {"meeting_id": mtid, "id": agid, "title": "UpdAg"})
    await tr.run(session, "delete agenda", "delete_meeting_agenda_item", {"meeting_id": mtid, "id": agid})

    sc = await tr.run(session, "create section", "create_meeting_section", {"meeting_id": mtid, "title": "Sec1", "position": 1})
    scid = extract_content(sc).get("id") if isinstance(extract_content(sc), dict) else None
    await tr.run(session, "get section", "get_meeting_section_by_id", {"meeting_id": mtid, "id": scid})
    await tr.run(session, "update section", "update_meeting_section", {"meeting_id": mtid, "id": scid, "title": "UpdSec"})
    await tr.run(session, "delete section", "delete_meeting_section", {"meeting_id": mtid, "id": scid})

    await tr.run(session, "update", "update_meeting", {"id": mtid, "title": "upd-" + mn})
    await tr.run(session, "delete", "delete_meeting", {"id": mtid})
    await asyncio.sleep(0.3)
    await tr.run(session, "verify-delete", "get_meeting_by_id", {"id": mtid}, expect="error")

    # ────────── NEWS ──────────
    nn = make_name("news")
    r = await tr.run(session, "create", "create_news", {"title": nn, "project_id": store.get("persistent_project_id")})
    nid = extract_content(r).get("id") if isinstance(extract_content(r), dict) else None
    await tr.run(session, "list", "list_news", {}, expect="success")
    await tr.run(session, "get", "get_news_by_id", {"id": nid})
    await tr.run(session, "update", "update_news", {"id": nid, "title": "upd-" + nn})
    await tr.run(session, "delete", "delete_news", {"id": nid})
    await asyncio.sleep(0.3)
    await tr.run(session, "verify-delete", "get_news_by_id", {"id": nid}, expect="error")

    # ────────── GRID ──────────
    gn = make_name("grid")
    scope_href = "/projects/demo-project/boards"
    pident = store.get("project_ident")
    scope_href = f"/projects/{pident}/boards" if pident else scope_href
    r = await tr.run(session, "create", "create_grid", {
        "page": gn, "row_count": 3, "column_count": 2, "scope_href": scope_href,
    })
    gid = extract_content(r).get("id") if isinstance(extract_content(r), dict) else None
    await tr.run(session, "list", "list_grids", {}, expect="success")
    await tr.run(session, "get", "get_grid_by_id", {"id": gid})
    await tr.run(session, "update", "update_grid", {"id": gid})
    await tr.run(session, "delete", "delete_grid", {"id": gid})
    await asyncio.sleep(0.3)
    await tr.run(session, "verify-delete", "get_grid_by_id", {"id": gid}, expect="error")

    # ────────── TIME ENTRY ──────────
    ten = make_name("te")
    te_ppid = store.get("persistent_project_id")
    te_wp_r = await tr.call(session, "create te wp", "create_work_package", {
        "subject": "te-" + ten, "project_id": te_ppid,
        "type_id": sid_type, "priority_id": sid_priority, "status_id": sid_status,
    })
    te_wpid = extract_content(te_wp_r).get("id") if isinstance(extract_content(te_wp_r), dict) else None
    te = await tr.run(session, "create", "create_time_entry", {
        "project_id": te_ppid, "work_package_id": te_wpid, "hours": "PT2H", "spent_on": "2026-06-27",
        "comment": ten,
    })
    teid = extract_content(te).get("id") if isinstance(extract_content(te), dict) else None
    await tr.run(session, "get", "get_time_entry_by_id", {"id": teid})
    await tr.run(session, "update", "update_time_entry", {"id": teid, "hours": "PT4H"})
    await tr.run(session, "delete", "delete_time_entry", {"id": teid})
    await asyncio.sleep(0.3)
    await tr.run(session, "verify-delete", "get_time_entry_by_id", {"id": teid}, expect="error")
    await tr.run(session, "list", "list_time_entries", {}, expect="success")

    # ────────── RECURRING MEETING ──────────
    rmn = make_name("rm")
    r = await tr.run(session, "create", "create_recurring_meeting", {
        "project_id": store.get("persistent_project_id"), "title": rmn, "frequency": "weekly",
        "start_time": "2026-07-01T10:00:00+00:00", "end_time": "2026-07-01T11:00:00+00:00",
        "days": [1],
    })
    rmid = extract_content(r).get("id") if isinstance(extract_content(r), dict) else None
    await tr.run(session, "list", "list_recurring_meetings", {}, expect="success")
    await tr.run(session, "get", "get_recurring_meeting_by_id", {"id": rmid})
    await tr.run(session, "update", "update_recurring_meeting", {"id": rmid, "title": "upd-" + rmn})
    await tr.run(session, "delete", "delete_recurring_meeting", {"id": rmid})
    await asyncio.sleep(0.3)
    await tr.run(session, "verify-delete", "get_recurring_meeting_by_id", {"id": rmid}, expect="error")

    # ────────── CLEANUP: Delete persistent project ──────────
    ppid = store.get("persistent_project_id")
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
        lr = await session.call_tool(lt, {"page_size": 100})
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
                    dt = del_map[domain]
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