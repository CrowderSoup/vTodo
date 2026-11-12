import os

os.environ.setdefault("VTODO_API_TOKEN", "test-token")

from mcp_server import server  # noqa: E402
from mcp_server.client import VtodoAPIError  # noqa: E402


class FakeClient:
    def __init__(self, error=None):
        self.error = error

    def export_tasks(self):
        if self.error:
            raise self.error
        return "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"


def test_export_tasks_returns_the_ics_text(monkeypatch):
    monkeypatch.setattr(server, "_current_client", lambda: FakeClient())
    assert server.export_tasks().startswith("BEGIN:VCALENDAR")


def test_export_tasks_reports_api_errors(monkeypatch):
    monkeypatch.setattr(server, "_current_client", lambda: FakeClient(error=VtodoAPIError(403, "Forbidden.")))
    assert "403" in server.export_tasks()
