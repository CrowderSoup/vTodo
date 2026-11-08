from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
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
# calls the API as each caller, with their own OAuth access token (checked by
# _VtodoTokenVerifier below), so there's no single client to build at import
# time in that case.
_stdio_client = (
    VtodoClient(_settings.api_url, _settings.api_token) if _settings.transport == "stdio" else None
)

# sha256(caller's OAuth access token) -> when its whoami check expires. Short
# and bounded: a token revoked in vtodo stops working here within the TTL, and
# a stream of distinct tokens can't grow the cache without limit. Only hashes
# are kept, so the process never holds a pile of live tokens.
_WHOAMI_CACHE_TTL_SECONDS = 60
_WHOAMI_CACHE_MAX_ENTRIES = 1024
_whoami_cache: OrderedDict[str, float] = OrderedDict()
# sha256(OAuth access token) -> VtodoClient sending that token as a Bearer, so
# a caller's tool calls reuse one pooled requests.Session. Bounded the same
# way; access tokens expire hourly, so old entries are dead weight.
_VTODO_CLIENTS_MAX_ENTRIES = 256
_vtodo_clients: OrderedDict[str, VtodoClient] = OrderedDict()


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _remember(cache: OrderedDict, key: str, value: Any, max_entries: int) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > max_entries:
        cache.popitem(last=False)


class _VtodoTokenVerifier:
    """Checks a remote MCP client's OAuth access token by asking Django's
    whoami endpoint (apps/api/views.py:WhoAmIView) whether it's valid. Tool
    calls then send that same token to the vtodo API, which enforces scope
    and audience itself, so no long-lived DRF token is involved."""

    async def verify_token(self, token: str) -> AccessToken | None:
        key = _token_key(token)
        expires_at = _whoami_cache.get(key)
        if expires_at is None or expires_at <= time.monotonic():
            _whoami_cache.pop(key, None)
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
            _remember(
                _whoami_cache,
                key,
                time.monotonic() + _WHOAMI_CACHE_TTL_SECONDS,
                _WHOAMI_CACHE_MAX_ENTRIES,
            )

        return AccessToken(token=token, client_id="vtodo", scopes=["tasks"])


def _current_client() -> VtodoClient:
    if _stdio_client is not None:
        return _stdio_client
    access_token = get_access_token()
    assert access_token is not None
    key = _token_key(access_token.token)
    client = _vtodo_clients.get(key)
    if client is None:
        client = VtodoClient(_settings.api_url, access_token.token, scheme="Bearer")
    _remember(_vtodo_clients, key, client, _VTODO_CLIENTS_MAX_ENTRIES)
    return client


def _resolve_workspace(client: VtodoClient, workspace: int | str | None) -> int | None:
    """A workspace id from an id or a name. None (or blank) means Personal."""
    if workspace is None or isinstance(workspace, bool):
        return None
    if isinstance(workspace, int):
        return workspace
    text = workspace.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    matches = [w for w in client.list_workspaces() if w["name"].casefold() == text.casefold()]
    if len(matches) == 1:
        return matches[0]["id"]
    if not matches:
        raise VtodoAPIError(404, f"No workspace named {text!r}. Call list_workspaces to see yours.")
    raise VtodoAPIError(400, f"More than one workspace is named {text!r}. Pass its id instead.")


def _resolve_assignee(client: VtodoClient, assignee: int | str) -> int:
    """A user id from an id or a name in list_assignees."""
    if isinstance(assignee, int) and not isinstance(assignee, bool):
        return assignee
    text = str(assignee).strip()
    if text.isdigit():
        return int(text)
    matches = [a for a in client.list_assignees() if (a.get("name") or "").casefold() == text.casefold()]
    if len(matches) == 1:
        return matches[0]["id"]
    if not matches:
        raise VtodoAPIError(404, f"No one named {text!r} can be assigned here. Call list_assignees.")
    raise VtodoAPIError(400, f"More than one assignee is named {text!r}. Pass their id instead.")


def _client(workspace: int | str | None = None) -> VtodoClient:
    client = _current_client()
    workspace_id = _resolve_workspace(client, workspace)
    return client if workspace_id is None else client.in_workspace(workspace_id)


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


# ── Workspace tools ────────────────────────────────────────────────────────────


@mcp.tool()
def list_workspaces() -> str:
    """List the workspaces you belong to and your role in each.

    Personal is yours alone. A shared workspace is one other people are in
    too. Pass a workspace's id or name as `workspace` to the task, comment and
    status tools to act in it; leave it out for Personal. Roles: a viewer can
    only read, a member can change tasks and comments, and an owner can also
    change statuses.
    """
    try:
        return _ok(_current_client().list_workspaces())
    except VtodoAPIError as e:
        return _err(e)


# ── Task tools ─────────────────────────────────────────────────────────────────


@mcp.tool()
def list_tasks(
    status: str | None = None,
    tags: list[str] | None = None,
    exclude_tags: list[str] | None = None,
    include_archived: bool = False,
    include_done: bool = False,
    assignee: str | None = None,
    claimable: bool = False,
    workspace: int | str | None = None,
) -> str:
    """List tasks, optionally filtered by status slug and/or tags.

    tags requires a task to have every listed tag; exclude_tags drops any task
    that has any of the listed tags (e.g. "show me everything except `home`").

    assignee is a user id, "me", or "none" for unassigned tasks. claimable
    keeps only tasks nobody holds a live claim on.

    Archived tasks are hidden unless include_archived is true. When no status
    is given, tasks in a done status are hidden unless include_done is true;
    passing a status (e.g. "done") always returns that status's tasks.

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    try:
        client = _client(workspace)
        tasks = client.list_tasks(
            status=status, tags=tags, exclude_tags=exclude_tags,
            assignee=assignee, claimable=claimable,
        )
        if not include_archived:
            tasks = [t for t in tasks if not t.get("is_archived")]
        if not status and not include_done:
            done_slugs = {s["slug"] for s in client.list_statuses() if s.get("is_done")}
            tasks = [t for t in tasks if t.get("status") not in done_slugs]
        return _ok(tasks)
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def get_task(id: int, workspace: int | str | None = None) -> str:
    """Get a single task by its numeric ID.

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    try:
        return _ok(_client(workspace).get_task(id))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def create_task(
    title: str,
    notes: str | None = None,
    status: str | None = None,
    due_date: str | None = None,
    due_time: str | None = None,
    duration_minutes: int | None = None,
    tags: list[str] | None = None,
    recurrence_days: int | None = None,
    recurrence_from: str | None = None,
    assignee: int | str | None = None,
    workspace: int | str | None = None,
) -> str:
    """Create a new task. due_date format: YYYY-MM-DD, due_time format: HH:MM.

    duration_minutes is only meaningful alongside due_time. To make the task
    recurring, set recurrence_days (how many days after it's next due) and
    optionally recurrence_from ("completion" (default) or "due_date" — which
    date the next recurrence counts forward from).

    assignee is a user id or name from list_assignees: a person, or an agent
    that will pick the task up by claiming it.

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    try:
        client = _client(workspace)
        return _ok(client.create_task(
            title,
            notes=notes,
            status=status,
            due_date=due_date,
            due_time=due_time,
            duration_minutes=duration_minutes,
            tags=tags,
            recurrence_days=recurrence_days,
            recurrence_from=recurrence_from,
            assignee=None if assignee is None else _resolve_assignee(client, assignee),
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
    due_time: str | None = None,
    duration_minutes: int | None = None,
    tags: list[str] | None = None,
    archived: bool | None = None,
    recurrence_days: int | None = None,
    recurrence_from: str | None = None,
    clear_notes: bool = False,
    clear_due_date: bool = False,
    clear_due_time: bool = False,
    clear_duration: bool = False,
    clear_recurrence: bool = False,
    assignee: int | str | None = None,
    clear_assignee: bool = False,
    workspace: int | str | None = None,
) -> str:
    """Update one or more fields on an existing task.

    Omitted fields are left unchanged. notes, due_date, due_time,
    duration_minutes, and recurrence_days can't be blanked out just by
    omitting them (that means "leave as is"), so pass clear_notes=True,
    clear_due_date=True, clear_due_time=True, clear_duration=True, or
    clear_recurrence=True to empty them. Clearing due_date also clears
    due_time (a time-of-day is meaningless without a date) — to reschedule
    to a new date and time in one call, pass due_date together with
    due_time (not clear_due_date). Pass archived=True/False to archive or
    unarchive the task without deleting it. due_time format: HH:MM.
    recurrence_from is "completion" (default) or "due_date". assignee is a
    user id or name from list_assignees; clear_assignee=True unassigns.

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    fields: dict[str, Any] = {}
    if title is not None:
        fields["title"] = title
    if clear_notes:
        fields["notes"] = ""
    elif notes is not None:
        fields["notes"] = notes
    if status is not None:
        fields["status"] = status
    if clear_due_date:
        fields["due_date"] = None
    elif due_date is not None:
        fields["due_date"] = due_date
    if clear_due_time:
        fields["due_time"] = None
    elif due_time is not None:
        fields["due_time"] = due_time
    # A cleared due_date always wins over an explicit due_time in the same
    # call: a bare time-of-day with no date is the exact inconsistency this
    # cascade exists to prevent, so clear_due_date can't be overridden by
    # also passing due_time (pass due_date, not clear_due_date, to reschedule).
    if fields.get("due_date", False) is None:
        fields["due_time"] = None
    if clear_duration:
        fields["duration_minutes"] = None
    elif duration_minutes is not None:
        fields["duration_minutes"] = duration_minutes
    if tags is not None:
        fields["tags"] = tags
    if archived is not None:
        fields["is_archived"] = archived
    if clear_recurrence:
        fields["recurrence_days"] = None
    elif recurrence_days is not None:
        fields["recurrence_days"] = recurrence_days
    if recurrence_from is not None:
        fields["recurrence_from"] = recurrence_from
    try:
        client = _client(workspace)
        if clear_assignee:
            fields["assignee"] = None
        elif assignee is not None:
            fields["assignee"] = _resolve_assignee(client, assignee)
        return _ok(client.update_task(id, **fields))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def delete_task(id: int, workspace: int | str | None = None) -> str:
    """Delete a task by its numeric ID.

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    try:
        _client(workspace).delete_task(id)
        return f"Task {id} deleted."
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def move_task(id: int, new_status: str, workspace: int | str | None = None) -> str:
    """Move a task to a different status column (pass the status slug).

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    try:
        return _ok(_client(workspace).move_task(id, new_status))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def reorder_tasks(ids: list[int], workspace: int | str | None = None) -> str:
    """Set the display order of a set of tasks.

    Pass task IDs in the order you want them to appear; the first ID becomes
    order 0, the next order 1, and so on. Tasks you don't own or that aren't
    in the list are left untouched.

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    try:
        _client(workspace).reorder_tasks(ids)
        return f"Reordered {len(ids)} task(s)."
    except VtodoAPIError as e:
        return _err(e)


# ── Assignment and claim tools ─────────────────────────────────────────────────


@mcp.tool()
def list_assignees(workspace: int | str | None = None) -> str:
    """List who tasks can be assigned to: people who can change the
    workspace's tasks (kind "human") and their agents (kind "agent").

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    try:
        return _ok(_client(workspace).list_assignees())
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def claim_task(id: int, lease_seconds: int | None = None, workspace: int | str | None = None) -> str:
    """Claim a task so no one else picks it up, or renew your claim.

    The claim lasts lease_seconds (default 900, 30 to 86400) and then lapses.
    Claim again before then to keep it. Fails with 409 while someone else
    holds it. Moving the task to a done status releases the claim.

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    try:
        return _ok(_client(workspace).claim_task(id, lease_seconds))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def release_task(id: int, workspace: int | str | None = None) -> str:
    """Drop the claim on a task so someone else can pick it up. A person can
    release anyone's claim; an agent only its own.

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    try:
        return _ok(_client(workspace).release_task(id))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def claim_next_task(lease_seconds: int | None = None, workspace: int | str | None = None) -> str:
    """Claim the next open task assigned to you that nobody is working on, in
    board order. Returns the task, or a message when there's nothing waiting.
    lease_seconds works as in claim_task.

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    try:
        task = _client(workspace).claim_next_task(lease_seconds)
    except VtodoAPIError as e:
        return _err(e)
    if task is None:
        return "No assigned tasks are waiting."
    return _ok(task)


# ── Comment tools ──────────────────────────────────────────────────────────────


@mcp.tool()
def list_comments(task_id: int, workspace: int | str | None = None) -> str:
    """List all comments on a task.

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    try:
        return _ok(_client(workspace).list_comments(task_id))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def add_comment(task_id: int, body: str, workspace: int | str | None = None) -> str:
    """Add a comment to a task without editing it.

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    try:
        return _ok(_client(workspace).add_comment(task_id, body))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def delete_comment(comment_id: int, workspace: int | str | None = None) -> str:
    """Delete a task comment by its ID.

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    try:
        _client(workspace).delete_comment(comment_id)
        return f"Comment {comment_id} deleted."
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def list_activity(task_id: int, workspace: int | str | None = None) -> str:
    """List a task's change history, oldest first: who (actor), where from
    (source: web, api, mcp, system), what (action, field) and the old/new
    values. Note text and comment bodies are not included, only that they
    changed.

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    try:
        return _ok(_client(workspace).list_activity(task_id))
    except VtodoAPIError as e:
        return _err(e)


# ── Status tools ───────────────────────────────────────────────────────────────


@mcp.tool()
def list_statuses(workspace: int | str | None = None) -> str:
    """List your task statuses.

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    try:
        return _ok(_client(workspace).list_statuses())
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def create_status(
    name: str,
    color: str | None = None,
    is_done: bool | None = None,
    workspace: int | str | None = None,
) -> str:
    """Create a new status. color is a hex string e.g. #ff0000.

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    try:
        return _ok(_client(workspace).create_status(name, color=color, is_done=is_done))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def update_status(
    slug: str,
    name: str | None = None,
    color: str | None = None,
    is_done: bool | None = None,
    workspace: int | str | None = None,
) -> str:
    """Update one or more fields on an existing status (identified by slug).

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    fields: dict[str, Any] = {}
    if name is not None:
        fields["name"] = name
    if color is not None:
        fields["color"] = color
    if is_done is not None:
        fields["is_done"] = is_done
    try:
        return _ok(_client(workspace).update_status(slug, **fields))
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def delete_status(slug: str, workspace: int | str | None = None) -> str:
    """Delete a status column by its slug.

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    try:
        _client(workspace).delete_status(slug)
        return f"Status '{slug}' deleted."
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def reorder_statuses(ids: list[int], workspace: int | str | None = None) -> str:
    """Set the display order of a set of status columns.

    Pass status IDs in the order you want them to appear. Reordering statuses
    you don't own is rejected.

    workspace is a workspace id or name from list_workspaces. Leave it out for Personal.
    """
    try:
        _client(workspace).reorder_statuses(ids)
        return f"Reordered {len(ids)} status(es)."
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
