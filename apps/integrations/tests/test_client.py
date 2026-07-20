from unittest.mock import MagicMock, patch

import pytest

from apps.integrations.models import SkylightConnection
from apps.integrations.skylight.client import (
    SkylightAPIError,
    SkylightAuthError,
    SkylightClient,
    refresh,
)
from apps.teams.models import Team


@pytest.fixture
def connection(db):
    team = Team.objects.create(name="Rocketry")
    conn = SkylightConnection(team=team, frame_id="frame123")
    conn.set_refresh_token("initial-refresh-tok")
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
def test_refresh_success_returns_tokens(mock_post):
    mock_post.return_value = _mock_response(
        200, {"access_token": "tok123", "refresh_token": "rotated-tok"}
    )
    result = refresh("initial-refresh-tok")
    assert result == {"access_token": "tok123", "refresh_token": "rotated-tok"}


@patch("apps.integrations.skylight.client.requests.post")
def test_refresh_failure_raises_auth_error(mock_post):
    mock_post.return_value = _mock_response(400, text='{"error":"invalid_grant"}')
    with pytest.raises(SkylightAuthError):
        refresh("bad-refresh-tok")


@patch("requests.Session.request")
@patch("apps.integrations.skylight.client.requests.post")
def test_client_authenticates_lazily_when_no_cached_token(mock_post, mock_request, connection):
    mock_post.return_value = _mock_response(
        200, {"access_token": "tok123", "refresh_token": "rotated-tok"}
    )
    mock_request.return_value = _mock_response(200, {"data": []})

    result = SkylightClient(connection).list_source_calendars()

    assert result == []
    assert mock_post.call_count == 1
    connection.refresh_from_db()
    assert connection.get_token() == "tok123"
    assert connection.get_refresh_token() == "rotated-tok"


@patch("requests.Session.request")
@patch("apps.integrations.skylight.client.requests.post")
def test_client_retries_once_on_401_then_succeeds(mock_post, mock_request, connection):
    connection.set_token("stale-token")
    connection.save()
    mock_post.return_value = _mock_response(
        200, {"access_token": "fresh-token", "refresh_token": "rotated-again-tok"}
    )
    mock_request.side_effect = [
        _mock_response(401, text="expired"),
        _mock_response(200, {"data": []}),
    ]

    result = SkylightClient(connection).list_source_calendars()

    assert result == []
    assert mock_request.call_count == 2
    connection.refresh_from_db()
    assert connection.get_token() == "fresh-token"
    assert connection.get_refresh_token() == "rotated-again-tok"


@patch("requests.Session.request")
def test_client_raises_api_error_on_4xx(mock_request, connection):
    connection.set_token("tok")
    connection.save()
    mock_request.return_value = _mock_response(422, text="bad request")

    with pytest.raises(SkylightAPIError):
        SkylightClient(connection).list_categories()


@patch("requests.Session.request")
@patch("apps.integrations.skylight.client.requests.post")
def test_refresh_token_rotates_across_sequential_authenticate_calls(mock_post, mock_request, connection):
    """Guards against a regression where the rotated refresh_token from one
    authenticate() call isn't actually persisted before the next call reads it."""
    mock_post.side_effect = [
        _mock_response(200, {"access_token": "tok-1", "refresh_token": "rotated-1"}),
        _mock_response(200, {"access_token": "tok-2", "refresh_token": "rotated-2"}),
    ]
    client = SkylightClient(connection)

    client.authenticate()
    connection.refresh_from_db()
    assert connection.get_refresh_token() == "rotated-1"

    client.authenticate()
    connection.refresh_from_db()
    assert connection.get_refresh_token() == "rotated-2"
