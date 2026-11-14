import asyncio
import os

import pytest

# server.py loads settings at import time and stdio mode requires a token.
os.environ.setdefault("VTODO_API_TOKEN", "test-token")

from mcp_server import server  # noqa: E402
from mcp_server.client import VtodoClient  # noqa: E402


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeAsyncClient:
    """Stands in for httpx.AsyncClient; counts whoami round trips. Set
    `error` to an exception to raise it instead of answering."""

    calls = 0
    status_code = 200
    error = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers, timeout):
        type(self).calls += 1
        if type(self).error is not None:
            raise type(self).error
        return FakeResponse(type(self).status_code, {"user_id": 1, "username": "u"})


@pytest.fixture(autouse=True)
def fake_whoami(monkeypatch):
    FakeAsyncClient.calls = 0
    FakeAsyncClient.status_code = 200
    FakeAsyncClient.error = None
    monkeypatch.setattr(server.httpx, "AsyncClient", FakeAsyncClient)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(server.asyncio, "sleep", no_sleep)
    server._whoami_cache.clear()
    yield
    server._whoami_cache.clear()


def verify(token):
    return asyncio.run(server._VtodoTokenVerifier().verify_token(token))


def test_verified_token_carries_only_the_callers_own_token():
    access = verify("oauth-token-a")

    assert access.token == "oauth-token-a"
    assert access.scopes == ["tasks"]
    assert not hasattr(access, "vtodo_api_token")


def test_rejected_token_is_not_cached():
    FakeAsyncClient.status_code = 401

    assert verify("revoked") is None
    assert verify("revoked") is None
    assert FakeAsyncClient.calls == 2


def test_cache_stores_hashes_not_tokens():
    verify("oauth-token-b")

    assert "oauth-token-b" not in server._whoami_cache
    assert server._token_key("oauth-token-b") in server._whoami_cache


def test_cached_check_expires_after_ttl(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(server.time, "monotonic", lambda: now[0])

    verify("oauth-token-c")
    verify("oauth-token-c")
    assert FakeAsyncClient.calls == 1

    now[0] += server._WHOAMI_CACHE_TTL_SECONDS + 1
    FakeAsyncClient.status_code = 401
    assert verify("oauth-token-c") is None
    assert FakeAsyncClient.calls == 2


def test_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(server, "_WHOAMI_CACHE_MAX_ENTRIES", 3)

    for i in range(5):
        verify(f"token-{i}")

    assert len(server._whoami_cache) == 3
    assert server._token_key("token-0") not in server._whoami_cache
    assert server._token_key("token-4") in server._whoami_cache


def test_client_sends_bearer_scheme_for_oauth_tokens():
    client = VtodoClient("https://vtodo.example.com", "oauth-token", scheme="Bearer")

    assert client._session.headers["Authorization"] == "Bearer oauth-token"


def test_client_defaults_to_drf_token_scheme():
    client = VtodoClient("https://vtodo.example.com", "drf-token")

    assert client._session.headers["Authorization"] == "Token drf-token"


def test_forbidden_token_is_rejected():
    FakeAsyncClient.status_code = 403

    assert verify("no-scope") is None


@pytest.mark.parametrize("status_code", [500, 502, 503, 429])
def test_whoami_errors_are_not_treated_as_a_bad_token(status_code):
    """A 401 here would make Claude refresh, and if that also failed, ask to
    sign in again. Server errors during a deploy must not do that."""
    FakeAsyncClient.status_code = status_code

    with pytest.raises(server.WhoamiUnavailable):
        verify("good-token")
    assert FakeAsyncClient.calls == server._WHOAMI_ATTEMPTS
    assert server._token_key("good-token") not in server._whoami_cache


def test_unreachable_whoami_is_not_treated_as_a_bad_token():
    FakeAsyncClient.error = server.httpx.ConnectError("connection refused")

    with pytest.raises(server.WhoamiUnavailable):
        verify("good-token")


def test_whoami_is_retried_once(monkeypatch):
    class FlakyClient(FakeAsyncClient):
        async def get(self, url, headers, timeout):
            type(self).calls += 1
            if type(self).calls == 1:
                raise server.httpx.ReadTimeout("slow")
            return FakeResponse(200)

    FlakyClient.calls = 0
    monkeypatch.setattr(server.httpx, "AsyncClient", FlakyClient)

    assert verify("good-token").token == "good-token"
    assert FlakyClient.calls == 2


def test_api_401_forgets_the_token(monkeypatch):
    import requests

    verify("replaced-token")
    key = server._token_key("replaced-token")
    client = VtodoClient(
        "https://vtodo.example.com",
        "replaced-token",
        scheme="Bearer",
        on_unauthorized=lambda: server._forget_token(key),
    )
    server._vtodo_clients[key] = client

    class Unauthorized:
        status_code = 401
        reason = "Unauthorized"
        text = ""

        def raise_for_status(self):
            raise requests.HTTPError()

        def json(self):
            return {"detail": "Invalid token."}

    monkeypatch.setattr(client._session, "request", lambda *a, **kw: Unauthorized())

    with pytest.raises(server.VtodoAPIError):
        client.list_workspaces()
    assert key not in server._whoami_cache
    assert key not in server._vtodo_clients


def test_api_timeout_becomes_an_error_result(monkeypatch):
    import requests

    client = VtodoClient("https://vtodo.example.com", "t", scheme="Bearer")

    def hang(*a, **kw):
        assert kw["timeout"]
        raise requests.ReadTimeout()

    monkeypatch.setattr(client._session, "request", hang)

    with pytest.raises(server.VtodoAPIError) as caught:
        client.list_workspaces()
    assert caught.value.status_code == 504


def test_tools_run_in_a_thread_and_still_see_the_callers_token(monkeypatch):
    """Tools run off the event loop. The caller's token comes from a
    contextvar, which has to reach the worker thread."""
    import threading

    from mcp.server.auth.middleware.auth_context import auth_context_var
    from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
    from mcp.server.auth.provider import AccessToken

    seen = {}

    def list_workspaces(self):
        seen["auth"] = self._session.headers["Authorization"]
        seen["thread"] = threading.current_thread()
        return []

    monkeypatch.setattr(server, "_stdio_client", None)
    monkeypatch.setattr(VtodoClient, "list_workspaces", list_workspaces)
    server._vtodo_clients.clear()

    async def call():
        auth_context_var.set(
            AuthenticatedUser(AccessToken(token="caller-token", client_id="vtodo", scopes=["tasks"]))
        )
        await server.mcp.call_tool("list_workspaces", {})

    asyncio.run(call())

    assert seen["auth"] == "Bearer caller-token"
    assert seen["thread"] is not threading.main_thread()
    server._vtodo_clients.clear()
