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
    """Stands in for httpx.AsyncClient; counts whoami round trips."""

    calls = 0
    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers, timeout):
        type(self).calls += 1
        return FakeResponse(type(self).status_code, {"user_id": 1, "username": "u"})


@pytest.fixture(autouse=True)
def fake_whoami(monkeypatch):
    FakeAsyncClient.calls = 0
    FakeAsyncClient.status_code = 200
    monkeypatch.setattr(server.httpx, "AsyncClient", FakeAsyncClient)
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
