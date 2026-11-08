import json
import os

import pytest

# server.py loads settings at import time and stdio mode requires a token.
os.environ.setdefault("VTODO_API_TOKEN", "test-token")

from mcp_server import server  # noqa: E402
from mcp_server.client import VtodoClient  # noqa: E402

ASSIGNEES = [
    {"id": 1, "name": "Aaron", "kind": "human", "parent": None},
    {"id": 5, "name": "Coder", "kind": "agent", "parent": 1},
    {"id": 6, "name": "Twin", "kind": "agent", "parent": 1},
    {"id": 7, "name": "twin", "kind": "agent", "parent": 1},
]


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)
        self.reason = "error"

    def json(self):
        return self._payload

    def raise_for_status(self):
        import requests

        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


@pytest.fixture
def api(monkeypatch):
    state = {"calls": [], "claim_next": FakeResponse(200, {"id": 42}), "claim": None}
    client = VtodoClient("http://vtodo.test", "tok")

    def fake_request(method, url, headers=None, **kwargs):
        state["calls"].append({"method": method, "url": url, "headers": headers or {}, **kwargs})
        if url.endswith("/assignees/"):
            return FakeResponse(payload=ASSIGNEES)
        if url.endswith("/claim-next/"):
            return state["claim_next"]
        if url.endswith("/claim/") and state["claim"] is not None:
            return state["claim"]
        return FakeResponse(payload=[] if method == "GET" else {"id": 3})

    monkeypatch.setattr(client._session, "request", fake_request)
    monkeypatch.setattr(server, "_current_client", lambda: client)
    return state


def test_assignee_by_name_is_resolved(api):
    server.update_task(3, assignee="coder")

    patch = api["calls"][-1]
    assert patch["method"] == "PATCH"
    assert patch["json"] == {"assignee": 5}


def test_assignee_by_id_skips_the_lookup(api):
    server.create_task("New", assignee=5)

    assert [c["url"] for c in api["calls"]] == ["http://vtodo.test/api/v1/tasks/"]
    assert api["calls"][0]["json"] == {"title": "New", "assignee": 5}


def test_clear_assignee_sends_null(api):
    server.update_task(3, clear_assignee=True)

    assert api["calls"][-1]["json"] == {"assignee": None}


def test_unknown_or_ambiguous_assignee_is_an_error(api):
    assert server.update_task(3, assignee="Nobody").startswith("Error 404")
    assert server.update_task(3, assignee="Twin").startswith("Error 400")
    assert not any(c["method"] == "PATCH" for c in api["calls"])


def test_claim_sends_the_lease_and_workspace(api):
    server.claim_task(3, lease_seconds=600, workspace=7)

    call = api["calls"][-1]
    assert call["url"].endswith("/tasks/3/claim/")
    assert call["json"] == {"lease_seconds": 600}
    assert call["headers"] == {"X-Workspace-Id": "7"}


def test_claim_conflict_is_passed_back(api):
    api["claim"] = FakeResponse(409, {"detail": "Claimed by Coder until later."})

    assert server.claim_task(3) == "Error 409: Claimed by Coder until later."


def test_claim_next_returns_the_task_or_says_none_are_waiting(api):
    assert json.loads(server.claim_next_task()) == {"id": 42}

    api["claim_next"] = FakeResponse(204, None)
    assert server.claim_next_task() == "No assigned tasks are waiting."


def test_release_and_list_assignees(api):
    server.release_task(3)
    assert api["calls"][-1]["url"].endswith("/tasks/3/release/")

    assert json.loads(server.list_assignees()) == ASSIGNEES


def test_list_tasks_passes_assignee_filters(api):
    server.list_tasks(status="todo", assignee="me", claimable=True)

    assert api["calls"][-1]["params"] == {"status": "todo", "assignee": "me", "claimable": "true"}
