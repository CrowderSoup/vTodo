from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import VtodoAPIError, VtodoClient
from .config import load_settings

mcp = FastMCP("vtodo")

# Initialised once when the module is imported (i.e. when the process starts).
_settings = load_settings()
_client = VtodoClient(_settings.api_url, _settings.api_token)


def _ok(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _err(e: VtodoAPIError) -> str:
    return f"Error {e.status_code}: {e.detail}"


# ── Task tools ─────────────────────────────────────────────────────────────────


@mcp.tool()
def list_tasks(status: str | None = None, tags: list[str] | None = None) -> str:
    """List tasks, optionally filtered by status slug and/or tags."""
    try:
        return _ok(_client.list_tasks(status=status, tags=tags))
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
) -> str:
    """Create a new task. due_date format: YYYY-MM-DD."""
    try:
        return _ok(_client.create_task(title, notes=notes, status=status, due_date=due_date, tags=tags))
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


# ── Status tools ───────────────────────────────────────────────────────────────


@mcp.tool()
def list_statuses() -> str:
    """List all task statuses (columns)."""
    try:
        return _ok(_client.list_statuses())
    except VtodoAPIError as e:
        return _err(e)


@mcp.tool()
def create_status(
    name: str,
    color: str | None = None,
    is_done: bool | None = None,
) -> str:
    """Create a new status column. color is a hex string e.g. #ff0000."""
    try:
        return _ok(_client.create_status(name, color=color, is_done=is_done))
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


def main() -> None:
    mcp.run(transport="stdio")
