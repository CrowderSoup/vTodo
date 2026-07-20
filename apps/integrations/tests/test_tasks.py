import pytest

from apps.integrations.models import SkylightConnection
from apps.integrations.skylight.client import SkylightAuthError
from apps.integrations.tasks import sync_all_skylight_connections
from apps.teams.models import Team


@pytest.fixture
def connection(db):
    team = Team.objects.create(name="Rocketry")
    conn = SkylightConnection(
        team=team,
        frame_id="frame123",
        calendar_account_id="cal-1",
        calendar_id="owner@gmail.com",
    )
    conn.set_refresh_token("initial-refresh-tok")
    conn.save()
    return conn


@pytest.mark.django_db
def test_sync_all_deactivates_connection_on_auth_error(monkeypatch, connection):
    def _raise(conn):
        raise SkylightAuthError("Skylight rejected the refresh token: 400")

    monkeypatch.setattr("apps.integrations.skylight.sync.sync_connection", _raise)

    sync_all_skylight_connections()

    connection.refresh_from_db()
    assert connection.is_active is False


@pytest.mark.django_db
def test_sync_all_keeps_connection_active_on_other_errors(monkeypatch, connection):
    def _raise(conn):
        raise RuntimeError("boom")

    monkeypatch.setattr("apps.integrations.skylight.sync.sync_connection", _raise)

    sync_all_skylight_connections()

    connection.refresh_from_db()
    assert connection.is_active is True
