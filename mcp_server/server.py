from __future__ import annotations

import json
import time
from datetime import date, datetime
from typing import Any

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from .client import VtodoAPIError, VtodoClient
from .config import load_settings

# Initialised once when the module is imported (i.e. when the process starts).
_settings = load_settings()

# stdio mode acts as a single fixed vtodo account (VTODO_API_TOKEN); sse mode
# resolves a different account per request from the caller's OAuth access
# token via _VtodoTokenVerifier below, so there's no single client to build
# at import time in that case.
_stdio_client = (
    VtodoClient(_settings.api_url, _settings.api_token) if _settings.transport == "stdio" else None
)

# Caller's OAuth access token -> their resolved vtodo DRF API token, so a
# whoami round-trip to Django only happens once per access token per this TTL.
_WHOAMI_CACHE_TTL_SECONDS = 300
_whoami_cache: dict[str, tuple[str, float]] = {}
# vtodo DRF API token -> VtodoClient, reused across calls/users so each gets
# its own pooled requests.Session instead of a fresh one per tool call.
_vtodo_clients: dict[str, VtodoClient] = {}


class _VtodoAccessToken(AccessToken):
    vtodo_api_token: str


class _VtodoTokenVerifier:
    """Resolves a Claude-issued OAuth access token to a vtodo account by
    asking Django's whoami endpoint who it belongs to
    (apps/api/views.py:WhoAmIView) — the vtodo API itself still only ever
    sees each user's regular DRF token, exactly as it does for stdio/local
    use."""

    async def verify_token(self, token: str) -> AccessToken | None:
        cached = _whoami_cache.get(token)
        if cached is None or cached[1] <= time.monotonic():
            async with httpx.AsyncClient() as http:
                try:
                    resp = await http.get(
                        _settings.whoami_url,
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=10,
                    )
                except httpx.HTTPError:
                    return None
            if resp.status_code != 200:
                return None
            api_token = resp.json().get("api_token")
            if not api_token:
                return None
            cached = (api_token, time.monotonic() + _WHOAMI_CACHE_TTL_SECONDS)
            _whoami_cache[token] = cached

        return _VtodoAccessToken(token=token, client_id="vtodo", scopes=["tasks"], vtodo_api_token=cached[0])


def _current_client() -> VtodoClient:
    if _stdio_client is not None:
        return _stdio_client
    access_token = get_access_token()
    assert isinstance(access_token, _VtodoAccessToken)
    client = _vtodo_clients.get(access_token.vtodo_api_token)
    if client is None:
        client = VtodoClient(_settings.api_url, access_token.vtodo_api_token)
        _vtodo_clients[access_token.vtodo_api_token] = client
    return client


mcp = FastMCP(
    "vtodo",
    host=_settings.host,
    token_verifier=_VtodoTokenVerifier() if _settings.transport == "sse" else None,
    auth=(
        AuthSettings(
            issuer_url=_settings.issuer_url,
            resource_server_url=_settings.resource_server_url,
            required_scopes=["tasks"],
        )
        if _settings.transport == "sse"
        else None
    ),
)


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
        return _ok(_current_client().list_tasks(status=status, tags=tags, team_id=team_id))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def get_task(id: int) -> str:
    """Get a single task by its numeric ID."""
    try:
        return _ok(_current_client().get_task(id))
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
        return _ok(_current_client().create_task(
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
        return _ok(_current_client().update_task(id, **fields))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def delete_task(id: int) -> str:
    """Delete a task by its numeric ID."""
    try:
        _current_client().delete_task(id)
        return f"Task {id} deleted."
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def move_task(id: int, new_status: str) -> str:
    """Move a task to a different status column (pass the status slug)."""
    try:
        return _ok(_current_client().move_task(id, new_status))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def assign_task(id: int, assignee_id: int | None = None) -> str:
    """Assign (or unassign, by omitting assignee_id) a team task to a team member.

    Only works on team tasks. Any member of the task's team can claim or
    reassign it — the assignee must also be a member of that team.
    """
    try:
        return _ok(_current_client().assign_task(id, assignee_id=assignee_id))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def list_task_activity(task_id: int) -> str:
    """List the assignment audit trail for a team task, oldest first."""
    try:
        return _ok(_current_client().list_task_activity(task_id))
    except VtodoAPIError as e:
        return _err(e)


# ── Comment tools ──────────────────────────────────────────────────────────────


@mcp.tool()
def list_comments(task_id: int) -> str:
    """List all comments on a task."""
    try:
        return _ok(_current_client().list_comments(task_id))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def add_comment(task_id: int, body: str) -> str:
    """Add a comment to a task without editing it."""
    try:
        return _ok(_current_client().add_comment(task_id, body))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def delete_comment(comment_id: int) -> str:
    """Delete a task comment by its ID."""
    try:
        _current_client().delete_comment(comment_id)
        return f"Comment {comment_id} deleted."
    except VtodoAPIError as e:
        return _err(e)


# ── Status tools ───────────────────────────────────────────────────────────────


@mcp.tool()
def list_statuses(team_id: int | None = None) -> str:
    """List task statuses. Without team_id, lists your personal statuses;
    pass team_id to list a team's shared statuses instead."""
    try:
        return _ok(_current_client().list_statuses(team_id=team_id))
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
        return _ok(_current_client().create_status(name, color=color, is_done=is_done, team_id=team_id))
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
        return _ok(_current_client().update_status(slug, **fields))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def delete_status(slug: str) -> str:
    """Delete a status column by its slug."""
    try:
        _current_client().delete_status(slug)
        return f"Status '{slug}' deleted."
    except VtodoAPIError as e:
        return _err(e)


# ── Team tools ─────────────────────────────────────────────────────────────────


@mcp.tool()
def list_teams() -> str:
    """List the teams you belong to."""
    try:
        return _ok(_current_client().list_teams())
    except VtodoAPIError as e:
        return _err(e)


# ── Resources ──────────────────────────────────────────────────────────────────


@mcp.resource("vtodo://statuses")
def resource_statuses() -> str:
    """All task statuses — useful context before creating or moving tasks."""
    try:
        return _ok(_current_client().list_statuses())
    except VtodoAPIError as e:
        return _err(e)


@mcp.resource("vtodo://tasks/today")
def resource_tasks_today() -> str:
    """Tasks whose due_date is today."""
    try:
        today = date.today().isoformat()
        tasks = _current_client().list_tasks()
        due_today = [t for t in tasks if t.get("due_date") == today]
        return _ok(due_today)
    except VtodoAPIError as e:
        return _err(e)


@mcp.resource("vtodo://tasks/overdue")
def resource_tasks_overdue() -> str:
    """Tasks past their due_date that have not been completed."""
    try:
        today = date.today().isoformat()
        tasks = _current_client().list_tasks()
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

        # Streamable HTTP is the current MCP transport standard; Claude.ai web
        # uses it. The route is registered at /mcp, which matches what DO
        # forwards when preserve_path_prefix is true for the /mcp ingress
        # rule. Bearer-token auth, the 401/WWW-Authenticate challenge, and the
        # RFC 9728 protected-resource metadata route are all handled by the
        # mcp SDK itself via the token_verifier/auth passed to FastMCP above.
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

            await http_app(scope, receive, send_with_cors)

        uvicorn.run(auth_app, host=_settings.host, port=_settings.port)
    else:
        mcp.run(transport="stdio")
