from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import VtodoAPIError, VtodoClient
from .config import load_settings

# Initialised once when the module is imported (i.e. when the process starts).
_settings = load_settings()
_client = VtodoClient(_settings.api_url, _settings.api_token)
mcp = FastMCP("vtodo", host=_settings.host)


def _ok(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _err(e: VtodoAPIError) -> str:
    return f"Error {e.status_code}: {e.detail}"


# ── Task tools ─────────────────────────────────────────────────────────────────


@mcp.tool()
def list_tasks(
    status: str | None = None, tags: list[str] | None = None, team_id: int | None = None
) -> str:
    """List tasks, optionally filtered by status slug, tags, and/or team.

    Without team_id, returns your personal tasks plus tasks from every team you
    belong to. Pass team_id to see only that team's shared tasks.
    """
    try:
        return _ok(_client.list_tasks(status=status, tags=tags, team_id=team_id))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def get_task(id: int) -> str:
    """Get a single task by its numeric ID."""
    try:
        return _ok(_client.get_task(id))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def create_task(
    title: str,
    notes: str | None = None,
    status: str | None = None,
    due_date: str | None = None,
    tags: list[str] | None = None,
    team_id: int | None = None,
) -> str:
    """Create a new task. due_date format: YYYY-MM-DD.

    Pass team_id to create a shared task on that team instead of a personal
    one — status must then be one of that team's status slugs (see
    list_statuses(team_id=...)). You must be a member of the team.
    """
    try:
        return _ok(_client.create_task(
            title, notes=notes, status=status, due_date=due_date, tags=tags, team_id=team_id
        ))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def update_task(
    id: int,
    title: str | None = None,
    notes: str | None = None,
    status: str | None = None,
    due_date: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Update one or more fields on an existing task."""
    fields: dict[str, Any] = {}
    if title is not None:
        fields["title"] = title
    if notes is not None:
        fields["notes"] = notes
    if status is not None:
        fields["status"] = status
    if due_date is not None:
        fields["due_date"] = due_date
    if tags is not None:
        fields["tags"] = tags
    try:
        return _ok(_client.update_task(id, **fields))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def delete_task(id: int) -> str:
    """Delete a task by its numeric ID."""
    try:
        _client.delete_task(id)
        return f"Task {id} deleted."
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def move_task(id: int, new_status: str) -> str:
    """Move a task to a different status column (pass the status slug)."""
    try:
        return _ok(_client.move_task(id, new_status))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def assign_task(id: int, assignee_id: int | None = None) -> str:
    """Assign (or unassign, by omitting assignee_id) a team task to a team member.

    Only works on team tasks. Any member of the task's team can claim or
    reassign it — the assignee must also be a member of that team.
    """
    try:
        return _ok(_client.assign_task(id, assignee_id=assignee_id))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def list_task_activity(task_id: int) -> str:
    """List the assignment audit trail for a team task, oldest first."""
    try:
        return _ok(_client.list_task_activity(task_id))
    except VtodoAPIError as e:
        return _err(e)


# ── Comment tools ──────────────────────────────────────────────────────────────


@mcp.tool()
def list_comments(task_id: int) -> str:
    """List all comments on a task."""
    try:
        return _ok(_client.list_comments(task_id))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def add_comment(task_id: int, body: str) -> str:
    """Add a comment to a task without editing it."""
    try:
        return _ok(_client.add_comment(task_id, body))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def delete_comment(comment_id: int) -> str:
    """Delete a task comment by its ID."""
    try:
        _client.delete_comment(comment_id)
        return f"Comment {comment_id} deleted."
    except VtodoAPIError as e:
        return _err(e)


# ── Status tools ───────────────────────────────────────────────────────────────


@mcp.tool()
def list_statuses(team_id: int | None = None) -> str:
    """List task statuses. Without team_id, lists your personal statuses;
    pass team_id to list a team's shared statuses instead."""
    try:
        return _ok(_client.list_statuses(team_id=team_id))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def create_status(
    name: str,
    color: str | None = None,
    is_done: bool | None = None,
    team_id: int | None = None,
) -> str:
    """Create a new status. color is a hex string e.g. #ff0000.

    Pass team_id to add a shared status to that team's workflow instead of
    your personal one. Any team member can do this.
    """
    try:
        return _ok(_client.create_status(name, color=color, is_done=is_done, team_id=team_id))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def update_status(
    slug: str,
    name: str | None = None,
    color: str | None = None,
    is_done: bool | None = None,
) -> str:
    """Update one or more fields on an existing status (identified by slug)."""
    fields: dict[str, Any] = {}
    if name is not None:
        fields["name"] = name
    if color is not None:
        fields["color"] = color
    if is_done is not None:
        fields["is_done"] = is_done
    try:
        return _ok(_client.update_status(slug, **fields))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def delete_status(slug: str) -> str:
    """Delete a status column by its slug."""
    try:
        _client.delete_status(slug)
        return f"Status '{slug}' deleted."
    except VtodoAPIError as e:
        return _err(e)


# ── Team tools ─────────────────────────────────────────────────────────────────


@mcp.tool()
def list_teams() -> str:
    """List the teams you belong to."""
    try:
        return _ok(_client.list_teams())
    except VtodoAPIError as e:
        return _err(e)


# ── Resources ──────────────────────────────────────────────────────────────────


@mcp.resource("vtodo://statuses")
def resource_statuses() -> str:
    """All task statuses — useful context before creating or moving tasks."""
    try:
        return _ok(_client.list_statuses())
    except VtodoAPIError as e:
        return _err(e)


@mcp.resource("vtodo://tasks/today")
def resource_tasks_today() -> str:
    """Tasks whose due_date is today."""
    try:
        today = date.today().isoformat()
        tasks = _client.list_tasks()
        due_today = [t for t in tasks if t.get("due_date") == today]
        return _ok(due_today)
    except VtodoAPIError as e:
        return _err(e)


@mcp.resource("vtodo://tasks/overdue")
def resource_tasks_overdue() -> str:
    """Tasks past their due_date that have not been completed."""
    try:
        today = date.today().isoformat()
        tasks = _client.list_tasks()
        overdue = [
            t for t in tasks
            if t.get("due_date") and t["due_date"] < today and not t.get("completed_at")
        ]
        return _ok(overdue)
    except VtodoAPIError as e:
        return _err(e)


_CORS_HEADERS = [
    (b"access-control-allow-origin", b"*"),
    (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
    (b"access-control-allow-headers", b"Authorization, Content-Type"),
]


def main() -> None:
    if _settings.transport == "sse":
        import uvicorn

        mcp_token = _settings.mcp_token
        # Streamable HTTP is the current MCP transport standard; Claude.ai web uses it.
        # The route is registered at /mcp, which matches what DO forwards when
        # preserve_path_prefix is true for the /mcp ingress rule.
        http_app = mcp.streamable_http_app()

        async def auth_app(scope, receive, send):
            if scope["type"] != "http":
                await http_app(scope, receive, send)
                return

            # Inject CORS headers into every HTTP response.
            async def send_with_cors(message):
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.extend(_CORS_HEADERS)
                    message = {**message, "headers": headers}
                await send(message)

            # Handle CORS preflight before auth so browsers can negotiate.
            if scope.get("method") == "OPTIONS":
                await send_with_cors({
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-length", b"0")],
                })
                await send({"type": "http.response.body", "body": b""})
                return

            # Unauthenticated health check for Kamal's proxy.
            if scope.get("path") == "/up":
                await send_with_cors({
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-length", b"2")],
                })
                await send({"type": "http.response.body", "body": b"OK"})
                return

            if mcp_token:
                headers = dict(scope.get("headers", []))
                auth = headers.get(b"authorization", b"").decode()
                query = scope.get("query_string", b"").decode()
                token_param = next(
                    (p[6:] for p in query.split("&") if p.startswith("token=")), ""
                )
                if auth != f"Bearer {mcp_token}" and token_param != mcp_token:
                    await send_with_cors({
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"text/plain")],
                    })
                    await send({"type": "http.response.body", "body": b"Unauthorized"})
                    return

            await http_app(scope, receive, send_with_cors)

        uvicorn.run(auth_app, host=_settings.host, port=_settings.port)
    else:
        mcp.run(transport="stdio")
