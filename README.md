# OpenProject MCP Server

This repository contains a Model Context Protocol (MCP) server that acts
as a secure, multi-tenant proxy between an AI Assistant and the OpenProject
backend API. It exposes **109 MCP tools** covering 17 resource domains
with full CRUD, workflow, and relationship management.

## ✨ Features

- **🔑 Identity Passthrough** — Extracts the `Authorization: Bearer <token>`
  header from incoming HTTP requests and forwards it to the OpenProject API
  without server-side authentication.
- **👥 Multi-Tenancy** — Uses Python `contextvars` to maintain thread-safe
  user identity isolation, ensuring all AI-driven actions are scoped to
  the authenticated user's permissions.
- **📊 Full OpenProject Coverage** — 109 tools mapped to OpenProject REST API
  endpoints across 17 resource domains.
- **⚡ TOON Optimization** — Bulk list responses are automatically compressed
  using TOON (Token-Optimized Object Notation) to reduce token consumption
  and maximize context window efficiency.
- **🚀 Efficient Gets** — GET responses return only commonly used fields by
  default. Full objects are available via an `include_all_fields` flag.
- **🧪 Comprehensive Testing** — 152 automated tests covering all tool
  domains, run via the test runner pipeline.
- **🏷️ Tool Annotations** — All tools expose standard MCP ToolAnnotations hints (readOnlyHint, destructiveHint, idempotentHint, openWorldHint). The tags field carries grouping metadata (basic/primary/advanced + servicename).

## 🔧 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENPROJECT_BASE_URL` | Yes | Docker-internal URL of the OpenProject API (e.g. `http://openproject-web:8080`). |
| `MCP_SERVER_PORT` | Yes | Port number the MCP server listens on |
| `ALLOW_ALL_AGGREGATE` | No | When `true`, aggregate listing tools honor the `include_all_fields` parameter. When `false` (default), the parameter is silently forced to `False` for aggregate list operations. |
| `IS_STATEFUL` | No | When `true`, uses stateful Streamable HTTP with session tracking. When `false` (default), uses stateless mode. |

## 📦 Installation & Local Development

1. Ensure you have Python 3.12+ installed.
2. Install dependencies:
    ```bash
    pip install fastmcp httpx pydantic uvicorn toon-mcp-server
    ```
3. Run the server:
    ```bash
    export OPENPROJECT_BASE_URL=http://openproject-web:8080
    export MCP_SERVER_PORT=80
    python -m src.main
    ```

## 🐳 Docker Deployment

Build and run the server using Docker:

```bash
docker build -t openproject-mcp:latest .
docker run -d --name openproject-mcp \
    -e OPENPROJECT_BASE_URL="http://openproject-web:8080" \
    -e MCP_SERVER_PORT=80 \
    -e ALLOW_ALL_AGGREGATE=false \
    openproject-mcp:latest
```

The MCP server serves at `http://openproject-mcp:80/mcp` (Streamable HTTP).

## ⚠️ Important Notes

- **📋 `include_all_fields`** — The `include_all_fields` parameter (available
  on all `get_*` and `list_*` tools) controls whether all available fields
  are included in responses. Defaults to `False` for performance; set to
  `True` only when additional fields are needed.
- **🔒 `ALLOW_ALL_AGGREGATE`** — Controls whether aggregate listing tools respect the `include_all_fields` parameter. When set to `false` (default), all aggregate list operations silently return only default fields regardless of the caller's request.
- **⚡ TOON Compression** — All bulk list responses are automatically
  compressed using TOON to reduce token consumption by 30–60%.
- **📝 Required Fields & Defaults** — Each `create_*` tool requires specific
  key fields. All other fields default to empty strings or reasonable values.
  The author/assignee field is automatically set to the authenticated user
  for most resources.

## 🛠️ API Tool Mapping

The server implements 109 MCP tools organized into the following categories:

### 🏗️ Project (6 tools)

- `list_projects` — List all projects
- `get_project_by_id` — Get a single project by ID
- `create_project` — Create a new project
- `update_project` — Update an existing project
- `delete_project` — Delete a project
- `copy_project` — Copy a project

### 📋 Work Package (13 tools)

- `list_work_packages` — List all work packages
- `get_work_package_by_id` — Get a single work package by ID
- `create_work_package` — Create a new work package
- `update_work_package` — Update an existing work package
- `delete_work_package` — Delete a work package
- `add_work_package_comment` — Add a comment to a work package
- `get_work_package_activities` — List activities on a work package
- `get_work_package_relations` — List relations for a work package
- `create_work_package_relation` — Create a relation to another work package
- `get_work_package_watchers` — List watchers of a work package
- `add_work_package_watcher` — Add a watcher to a work package
- `remove_work_package_watcher` — Remove a watcher from a work package
- `list_work_package_attachments` — List attachment metadata for a work package

### 🔖 Version (5 tools)

- `list_versions` — List all versions
- `get_version_by_id` — Get a single version by ID
- `create_version` — Create a new version
- `update_version` — Update an existing version
- `delete_version` — Delete a version

### 👤 Membership (5 tools)

- `list_memberships` — List all memberships
- `get_membership_by_id` — Get a single membership by ID
- `create_membership` — Create a new membership
- `update_membership` — Update an existing membership
- `delete_membership` — Delete a membership

### 🧑 User (5 tools)

- `list_users` — List all users
- `get_user_by_id` — Get a single user by ID
- `create_user` — Create a new user
- `update_user` — Update an existing user
- `delete_user` — Delete a user

### 👥 Group (5 tools)

- `list_groups` — List all groups
- `get_group_by_id` — Get a single group by ID
- `create_group` — Create a new group
- `update_group` — Update an existing group
- `delete_group` — Delete a group

### 📊 Reference Data (10 tools)

- `list_statuses` — List all statuses
- `get_status_by_id` — Get a single status by ID
- `list_types` — List all types
- `get_type_by_id` — Get a single type by ID
- `list_priorities` — List all priorities
- `get_priority_by_id` — Get a single priority by ID
- `list_roles` — List all roles
- `get_role_by_id` — Get a single role by ID
- `list_principals` — List all principals
- `get_principal_by_id` — Get a single principal by ID

### 📅 Meeting (15 tools)

- `list_meetings` — List all meetings
- `get_meeting_by_id` — Get a single meeting by ID
- `create_meeting` — Create a new meeting
- `update_meeting` — Update an existing meeting
- `delete_meeting` — Delete a meeting
- `list_meeting_agenda_items` — List agenda items for a meeting
- `create_meeting_agenda_item` — Create an agenda item
- `get_meeting_agenda_item_by_id` — Get a single agenda item by ID
- `update_meeting_agenda_item` — Update an agenda item
- `delete_meeting_agenda_item` — Delete an agenda item
- `list_meeting_sections` — List sections for a meeting
- `create_meeting_section` — Create a meeting section
- `get_meeting_section_by_id` — Get a single section by ID
- `update_meeting_section` — Update a section
- `delete_meeting_section` — Delete a section

### 🔄 Recurring Meeting (5 tools)

- `list_recurring_meetings` — List all recurring meetings
- `get_recurring_meeting_by_id` — Get a single recurring meeting by ID
- `create_recurring_meeting` — Create a new recurring meeting
- `update_recurring_meeting` — Update an existing recurring meeting
- `delete_recurring_meeting` — Delete a recurring meeting

### ⏱️ Time Entry (5 tools)

- `list_time_entries` — List all time entries
- `get_time_entry_by_id` — Get a single time entry by ID
- `create_time_entry` — Create a new time entry
- `update_time_entry` — Update an existing time entry
- `delete_time_entry` — Delete a time entry

### 📰 News (5 tools)

- `list_news` — List all news
- `get_news_by_id` — Get a single news by ID
- `create_news` — Create a new news
- `update_news` — Update an existing news
- `delete_news` — Delete a news

### 📐 Grid (5 tools)

- `list_grids` — List all grids
- `get_grid_by_id` — Get a single grid by ID
- `create_grid` — Create a new grid
- `update_grid` — Update an existing grid
- `delete_grid` — Delete a grid

### 🗓️ Calendar (5 tools)

- `list_days` — List all days in a date range
- `list_non_working_days` — List all non-working days
- `get_non_working_day_by_date` — Get a non-working day by date
- `list_week_days` — List all week days
- `get_week_day_by_number` — Get a week day by number

### 📄 Document (3 tools)

- `list_documents` — List all documents
- `get_document_by_id` — Get a single document by ID
- `update_document` — Update an existing document

### 🔔 Notification & Reminder (6 tools)

- `list_notifications` — List all notifications
- `get_notification_by_id` — Get a single notification by ID
- `create_reminder` — Create a reminder on a work package
- `list_reminders` — List all reminders
- `update_reminder` — Update a reminder
- `delete_reminder` — Delete a reminder

### 🔍 Read-Only Resources (7 tools)

- `list_project_categories` — List categories for a project
- `get_category_by_id` — Get a single category by ID
- `list_project_budgets` — List budgets for a project
- `get_budget_by_id` — Get a single budget by ID
- `get_wiki_page_by_id` — Get a single wiki page by ID
- `get_attachment_by_id` — Get a single attachment by ID
- `get_cost_type_by_id` — Get a single cost type by ID

### 🛠️ Utility (4 tools)

- `toggle_emoji_reaction` — Toggle an emoji reaction on an activity
- `list_emoji_reactions` — List emoji reactions on an activity
- `get_job_status` — Get the status of an async job
- `health_check` — Basic server health check
