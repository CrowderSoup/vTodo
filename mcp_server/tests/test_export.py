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


class FakeImportClient:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def import_tasks(self, ics, dry_run=True):
        self.calls.append((ics, dry_run))
        if self.error:
            raise self.error
        return {"dry_run": dry_run, "summary": "1 new, 0 updated, 0 skipped"}


def test_import_tasks_defaults_to_a_dry_run(monkeypatch):
    fake = FakeImportClient()
    monkeypatch.setattr(server, "_current_client", lambda: fake)
    out = server.import_tasks("BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")
    assert fake.calls[0][1] is True
    assert "1 new, 0 updated, 0 skipped" in out


def test_import_tasks_can_write(monkeypatch):
    fake = FakeImportClient()
    monkeypatch.setattr(server, "_current_client", lambda: fake)
    server.import_tasks("x", dry_run=False)
    assert fake.calls[0][1] is False


def test_import_tasks_reports_api_errors(monkeypatch):
    fake = FakeImportClient(error=VtodoAPIError(400, "That isn't an iCalendar (.ics) file."))
    monkeypatch.setattr(server, "_current_client", lambda: fake)
    assert "400" in server.import_tasks("x")
