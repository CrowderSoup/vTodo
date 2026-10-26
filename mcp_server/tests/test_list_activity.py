import json
import os

import pytest

os.environ.setdefault("VTODO_API_TOKEN", "test-token")

from mcp_server import server  # noqa: E402
from mcp_server.client import VtodoAPIError, VtodoClient  # noqa: E402


class FakeClient:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error
        self.calls = []

    def list_activity(self, task_id):
        self.calls.append(task_id)
        if self.error:
            raise self.error
        return self.rows


def test_list_activity_returns_rows(monkeypatch):
    fake = FakeClient(rows=[{"id": 1, "action": "created"}])
    monkeypatch.setattr(server, "_current_client", lambda: fake)
    assert json.loads(server.list_activity(7)) == [{"id": 1, "action": "created"}]
    assert fake.calls == [7]


def test_list_activity_reports_api_errors(monkeypatch):
    fake = FakeClient(error=VtodoAPIError(404, "Not found."))
    monkeypatch.setattr(server, "_current_client", lambda: fake)
    assert "404" in server.list_activity(7)


def test_client_labels_requests_as_mcp():
    client = VtodoClient("http://example.test", "tok")
    assert client._session.headers["X-Vtodo-Client"] == "mcp"
