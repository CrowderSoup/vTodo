import json
import os

import pytest

# server.py loads settings at import time and stdio mode requires a token.
os.environ.setdefault("VTODO_API_TOKEN", "test-token")

from mcp_server import server  # noqa: E402
from mcp_server.client import VtodoClient  # noqa: E402

WORKSPACES = [
    {"id": 1, "name": "Personal", "kind": "personal", "role": "owner", "can_write": True, "can_admin": True},
    {"id": 7, "name": "Aaron & Azure", "kind": "shared", "role": "member", "can_write": True, "can_admin": False},
    {"id": 9, "name": "Twins", "kind": "shared", "role": "viewer", "can_write": False, "can_admin": False},
    {"id": 10, "name": "twins", "kind": "shared", "role": "viewer", "can_write": False, "can_admin": False},
]


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else []
        self.text = json.dumps(self._payload)
        self.reason = "error"

    def json(self):
        return self._payload

    def raise_for_status(self):
        import requests

        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


@pytest.fixture
def calls(monkeypatch):
    """Use a real VtodoClient, recording each request instead of sending it."""
    recorded = []
    client = VtodoClient("http://vtodo.test", "tok")

    def fake_request(method, url, headers=None, **kwargs):
        recorded.append({"method": method, "url": url, "headers": headers or {}, **kwargs})
        if url.endswith("/workspaces/"):
            return FakeResponse(payload=WORKSPACES)
        if method == "POST" and url.endswith("/statuses/"):
            return FakeResponse(403, {"detail": "You can't change this workspace."})
        return FakeResponse(payload={"id": 1} if method != "GET" else [])

    monkeypatch.setattr(client._session, "request", fake_request)
    monkeypatch.setattr(server, "_current_client", lambda: client)
    return recorded


def _task_calls(calls):
    return [c for c in calls if not c["url"].endswith("/workspaces/")]


def test_list_workspaces_returns_roles(calls):
    result = json.loads(server.list_workspaces())

    assert result == WORKSPACES
    assert "X-Workspace-Id" not in calls[0]["headers"]


def test_tools_default_to_personal(calls):
    server.list_tasks()
    server.get_task(3)
    server.create_task("New")
    server.list_statuses()

    assert calls, "expected requests"
    assert all("X-Workspace-Id" not in c["headers"] for c in calls)
    assert not any(c["url"].endswith("/workspaces/") for c in calls)


def test_workspace_id_is_sent_as_header(calls):
    server.update_task(3, title="Renamed", workspace=7)
    server.move_task(3, "done", workspace="7")
    server.add_comment(3, "hi", workspace=7)

    assert [c["headers"] for c in calls] == [{"X-Workspace-Id": "7"}] * 3


def test_workspace_name_is_resolved_case_insensitively(calls):
    server.list_tasks(status="todo", workspace="aaron & azure")

    task_calls = _task_calls(calls)
    assert len(task_calls) == 1
    assert task_calls[0]["headers"] == {"X-Workspace-Id": "7"}


def test_unknown_workspace_name_is_an_error(calls):
    result = server.list_tasks(workspace="Nope")

    assert result.startswith("Error 404")
    assert "list_workspaces" in result
    assert _task_calls(calls) == []


def test_ambiguous_workspace_name_asks_for_the_id(calls):
    result = server.get_task(3, workspace="Twins")

    assert result.startswith("Error 400")
    assert _task_calls(calls) == []


def test_role_errors_from_the_api_are_passed_back(calls):
    result = server.create_status("Blocked", workspace=7)

    assert result == "Error 403: You can't change this workspace."
    assert calls[-1]["headers"] == {"X-Workspace-Id": "7"}


def test_scoped_client_leaves_the_original_alone():
    client = VtodoClient("http://vtodo.test", "tok")
    scoped = client.in_workspace(7)

    assert scoped._headers == {"X-Workspace-Id": "7"}
    assert client._headers == {}
    assert scoped._session is client._session
    assert client.in_workspace(None) is client


def test_every_task_and_status_tool_takes_a_workspace():
    import inspect

    names = [
        "list_tasks", "get_task", "create_task", "update_task", "delete_task",
        "move_task", "reorder_tasks", "list_comments", "add_comment",
        "delete_comment", "list_activity", "list_statuses", "create_status",
        "update_status", "delete_status", "reorder_statuses",
        "list_assignees", "claim_task", "release_task", "claim_next_task",
    ]
    for name in names:
        params = inspect.signature(getattr(server, name)).parameters
        assert params["workspace"].default is None, name
