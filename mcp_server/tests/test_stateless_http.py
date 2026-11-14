"""The streamable HTTP endpoint keeps no sessions. A tool call has to work
with no session id, or with one from a process that no longer exists (as
after a deploy), so the connector doesn't break mid-conversation."""

import os

import pytest

os.environ.setdefault("VTODO_API_TOKEN", "test-token")

from starlette.testclient import TestClient  # noqa: E402

from mcp_server import server  # noqa: E402

HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "Mcp-Protocol-Version": "2025-06-18",
}


@pytest.fixture
def http(monkeypatch):
    monkeypatch.setattr(server.VtodoClient, "list_workspaces", lambda self: [{"id": 1, "name": "Personal"}])
    # The session manager can only run once per instance, so build a fresh one.
    monkeypatch.setattr(server.mcp, "_session_manager", None)
    with TestClient(server.mcp.streamable_http_app(), base_url="http://localhost") as client:
        yield client


def _call(http, headers):
    return http.post(
        "/mcp",
        headers={**HEADERS, **headers},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "list_workspaces", "arguments": {}},
        },
    )


def test_tool_call_without_a_session_id(http):
    response = _call(http, {})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "Personal" in response.json()["result"]["content"][0]["text"]


def test_tool_call_with_a_session_id_from_before_a_restart(http):
    response = _call(http, {"Mcp-Session-Id": "0123456789abcdef0123456789abcdef"})

    assert response.status_code == 200


def test_tools_list_without_a_session_id(http):
    response = http.post(
        "/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )

    assert response.status_code == 200
    names = {t["name"] for t in response.json()["result"]["tools"]}
    assert {"list_workspaces", "list_tasks", "import_tasks"} <= names
