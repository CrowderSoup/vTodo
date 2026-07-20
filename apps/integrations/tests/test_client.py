from unittest.mock import MagicMock, patch

import pytest

from apps.integrations.models import SkylightConnection
from apps.integrations.skylight.client import (
    SkylightAPIError,
    SkylightAuthError,
    SkylightClient,
    login,
)
from apps.teams.models import Team


@pytest.fixture
def connection(db):
    team = Team.objects.create(name="Rocketry")
    conn = SkylightConnection(team=team, frame_id="frame123", email="owner@example.com")
    conn.set_password("hunter2")
    conn.save()
    return conn


def _mock_response(status_code, json_data=None, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.content = b"{}" if json_data is not None else b""
    response.json.return_value = json_data or {}
    response.text = text
    return response


@patch("apps.integrations.skylight.client.requests.post")
def test_login_success_returns_token(mock_post):
    mock_post.return_value = _mock_response(200, {"data": {"attributes": {"token": "tok123"}}})
    assert login("a@example.com", "pw") == "tok123"


@patch("apps.integrations.skylight.client.requests.post")
def test_login_failure_raises_auth_error(mock_post):
    mock_post.return_value = _mock_response(401)
    with pytest.raises(SkylightAuthError):
        login("a@example.com", "wrong")


@patch("requests.Session.request")
@patch("apps.integrations.skylight.client.requests.post")
def test_client_authenticates_lazily_when_no_cached_token(mock_post, mock_request, connection):
    mock_post.return_value = _mock_response(200, {"data": {"attributes": {"token": "tok123"}}})
    mock_request.return_value = _mock_response(200, {"data": []})

    result = SkylightClient(connection).list_source_calendars()

    assert result == []
    assert mock_post.call_count == 1
    connection.refresh_from_db()
    assert connection.get_token() == "tok123"


@patch("requests.Session.request")
@patch("apps.integrations.skylight.client.requests.post")
def test_client_retries_once_on_401_then_succeeds(mock_post, mock_request, connection):
    connection.set_token("stale-token")
    connection.save()
    mock_post.return_value = _mock_response(200, {"data": {"attributes": {"token": "fresh-token"}}})
    mock_request.side_effect = [
        _mock_response(401, text="expired"),
        _mock_response(200, {"data": []}),
    ]

    result = SkylightClient(connection).list_source_calendars()

    assert result == []
    assert mock_request.call_count == 2
    connection.refresh_from_db()
    assert connection.get_token() == "fresh-token"


@patch("requests.Session.request")
def test_client_raises_api_error_on_4xx(mock_request, connection):
    connection.set_token("tok")
    connection.save()
    mock_request.return_value = _mock_response(422, text="bad request")

    with pytest.raises(SkylightAPIError):
        SkylightClient(connection).list_categories()
