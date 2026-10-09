import json
import os

import pytest

# server.py loads settings at import time and stdio mode requires a token.
os.environ.setdefault("VTODO_API_TOKEN", "test-token")

from mcp_server import server  # noqa: E402
from mcp_server.client import VtodoAPIError  # noqa: E402


class FakeClient:
    def __init__(self, tasks, statuses):
        self._tasks = tasks
        self._statuses = statuses
        self.list_statuses_calls = 0
        self.raise_on_statuses = None

    def list_tasks(self, status=None, tags=None, exclude_tags=None):
        if not status:
            return self._tasks
        return [t for t in self._tasks if t["status"] == status]

    def list_statuses(self):
        self.list_statuses_calls += 1
        if self.raise_on_statuses:
            raise self.raise_on_statuses
        return self._statuses


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient(
        tasks=[
            {"id": 1, "status": "todo", "is_archived": False},
            {"id": 2, "status": "todo", "is_archived": True},
            {"id": 3, "status": "done", "is_archived": False},
        ],
        statuses=[
            {
                "id": 10,
                "name": "To Do",
                "slug": "todo",
                "order": 0,
                "color": "#999999",
                "is_done": False,
            },
            {
                "id": 11,
                "name": "Done",
                "slug": "done",
                "order": 1,
                "color": "#00aa00",
                "is_done": True,
            },
        ],
    )
    monkeypatch.setattr(server, "_current_client", lambda: client)
    return client


def _ids(result):
    return {t["id"] for t in json.loads(result)}


def test_archived_excluded_by_default(fake_client):
    assert 2 not in _ids(server.list_tasks())


def test_archived_included_when_requested(fake_client):
    assert 2 in _ids(server.list_tasks(include_archived=True))


def test_done_excluded_without_status(fake_client):
    assert 3 not in _ids(server.list_tasks())


def test_done_excluded_when_status_is_empty_string(fake_client):
    assert 3 not in _ids(server.list_tasks(status=""))


def test_done_included_with_include_done(fake_client):
    assert 3 in _ids(server.list_tasks(include_done=True))


def test_done_returned_when_status_is_done(fake_client):
    assert _ids(server.list_tasks(status="done")) == {3}


def test_list_statuses_skipped_when_status_given(fake_client):
    server.list_tasks(status="todo")
    assert fake_client.list_statuses_calls == 0


def test_list_statuses_skipped_when_include_done(fake_client):
    server.list_tasks(include_done=True)
    assert fake_client.list_statuses_calls == 0


def test_list_statuses_error_returns_error_string(fake_client):
    fake_client.raise_on_statuses = VtodoAPIError(500, "boom")
    result = server.list_tasks()
    assert result == "Error 500: boom"
