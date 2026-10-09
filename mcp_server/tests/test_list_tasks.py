import json
import os

import pytest

# server.py loads settings at import time and stdio mode requires a token.
os.environ.setdefault("VTODO_API_TOKEN", "test-token")

from mcp_server import server  # noqa: E402


class FakeClient:
    def __init__(self, tasks, statuses):
        self._tasks = tasks
        self._statuses = statuses

    def list_tasks(self, status=None, tags=None, exclude_tags=None):
        if status is None:
            return self._tasks
        done = {s["id"] for s in self._statuses if s["slug"] == status}
        return [t for t in self._tasks if t["status"] in done]

    def list_statuses(self):
        return self._statuses


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient(
        tasks=[
            {"id": 1, "status": 1, "is_archived": False},
            {"id": 2, "status": 1, "is_archived": True},
            {"id": 3, "status": 2, "is_archived": False},
        ],
        statuses=[
            {"id": 1, "slug": "todo", "is_done": False},
            {"id": 2, "slug": "done", "is_done": True},
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


def test_done_included_with_include_done(fake_client):
    assert 3 in _ids(server.list_tasks(include_done=True))


def test_done_returned_when_status_is_done(fake_client):
    assert _ids(server.list_tasks(status="done")) == {3}
