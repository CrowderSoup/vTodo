from datetime import date

import pytest

from apps.integrations.google_calendar import sync
from apps.integrations.google_calendar.client import GoogleCalendarAPIError, GoogleCalendarAuthError
from apps.integrations.models import ExternalLink, GoogleCalendarConnection
from apps.tasks.models import Task
from apps.teams.models import Team, TeamMembership
from apps.users.models import User


class FakeGoogleCalendarClient:
    """Records calls instead of hitting the network, so sync_connection's
    decisions (create/update/delete) can be asserted on directly."""

    def __init__(self, connection):
        self.connection = connection
        self.created = []
        self.updated = []
        self.deleted = []
        self._next_id = 1

    def create_event(self, calendar_id, payload):
        event_id = f"evt-{self._next_id}"
        self._next_id += 1
        self.created.append((event_id, payload))
        return {"id": event_id}

    def update_event(self, calendar_id, event_id, payload):
        self.updated.append((event_id, payload))
        return {"id": event_id}

    def delete_event(self, calendar_id, event_id):
        self.deleted.append(event_id)


@pytest.fixture
def fake_client(monkeypatch):
    instances = []

    def _make(connection):
        client = FakeGoogleCalendarClient(connection)
        instances.append(client)
        return client

    monkeypatch.setattr(sync, "GoogleCalendarClient", _make)
    return instances


@pytest.fixture
def connection(db):
    user = User.objects.create_user()
    return GoogleCalendarConnection.objects.create(user=user, calendar_id="cal-1", refresh_token_encrypted="x")


@pytest.mark.django_db
def test_personal_task_creates_event(connection, fake_client):
    Task.objects.create(user=connection.user, title="Renew passport", due_date=date(2026, 1, 1))

    sync.sync_connection(connection)

    client = fake_client[0]
    assert len(client.created) == 1
    link = ExternalLink.objects.get(provider=ExternalLink.Provider.GOOGLE_CALENDAR)
    assert link.external_id == client.created[0][0]


@pytest.mark.django_db
def test_team_task_assigned_to_user_creates_event(connection, fake_client):
    team = Team.objects.create(name="Ops")
    TeamMembership.objects.create(team=team, user=connection.user, role=TeamMembership.ROLE_MEMBER)
    Task.objects.create(
        user=connection.user, team=team, assignee=connection.user, title="Ship release", due_date=date(2026, 1, 1)
    )

    sync.sync_connection(connection)

    assert len(fake_client[0].created) == 1


@pytest.mark.django_db
def test_team_task_not_assigned_to_user_is_not_synced(connection, fake_client):
    other_user = User.objects.create_user()
    team = Team.objects.create(name="Ops")
    TeamMembership.objects.create(team=team, user=connection.user, role=TeamMembership.ROLE_MEMBER)
    Task.objects.create(user=other_user, team=team, title="Not mine", due_date=date(2026, 1, 1))

    sync.sync_connection(connection)

    assert fake_client[0].created == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"due_date": None},
        {"is_archived": True},
        {"completed_at": "2026-01-01T00:00:00+00:00"},
    ],
)
@pytest.mark.django_db
def test_ineligible_task_is_not_synced(connection, fake_client, overrides):
    from django.utils.dateparse import parse_datetime

    fields = {"user": connection.user, "title": "Not eligible", "due_date": date(2026, 1, 1)}
    if "completed_at" in overrides:
        overrides["completed_at"] = parse_datetime(overrides["completed_at"])
    fields.update(overrides)
    Task.objects.create(**fields)

    sync.sync_connection(connection)

    assert fake_client[0].created == []


@pytest.mark.django_db
def test_sync_relevant_change_triggers_update(connection, fake_client):
    task = Task.objects.create(user=connection.user, title="Renew passport", due_date=date(2026, 1, 1))
    sync.sync_connection(connection)

    task.title = "Renew passport ASAP"
    task.save(update_fields=["title"])
    sync.sync_connection(connection)

    # A fresh GoogleCalendarClient is built on every sync_connection call, so
    # the second run's activity is on the second recorded instance.
    assert len(fake_client[1].updated) == 1


@pytest.mark.django_db
def test_unrelated_change_does_not_trigger_update(connection, fake_client):
    task = Task.objects.create(user=connection.user, title="Renew passport", due_date=date(2026, 1, 1))
    sync.sync_connection(connection)

    task.tags = ["urgent"]
    task.order = 5
    task.save(update_fields=["tags", "order"])
    sync.sync_connection(connection)

    assert fake_client[1].updated == []


@pytest.mark.django_db
def test_task_becoming_ineligible_deletes_event_and_link(connection, fake_client):
    task = Task.objects.create(user=connection.user, title="Renew passport", due_date=date(2026, 1, 1))
    sync.sync_connection(connection)

    task.is_archived = True
    task.save(update_fields=["is_archived"])
    sync.sync_connection(connection)

    assert len(fake_client[1].deleted) == 1
    assert not ExternalLink.objects.filter(provider=ExternalLink.Provider.GOOGLE_CALENDAR).exists()


@pytest.mark.django_db
def test_auth_error_deactivates_connection(connection, monkeypatch):
    Task.objects.create(user=connection.user, title="Renew passport", due_date=date(2026, 1, 1))

    def _raise(*args, **kwargs):
        raise GoogleCalendarAuthError("refresh token revoked")

    broken_client = FakeGoogleCalendarClient(connection)
    broken_client.create_event = _raise
    monkeypatch.setattr(sync, "GoogleCalendarClient", lambda c: broken_client)

    with pytest.raises(GoogleCalendarAuthError):
        sync.sync_connection(connection)

    connection.refresh_from_db()
    assert connection.is_active is False
    assert connection.last_sync_error == "refresh token revoked"


@pytest.mark.django_db
def test_api_error_records_last_sync_error_without_deactivating(connection, monkeypatch):
    Task.objects.create(user=connection.user, title="Renew passport", due_date=date(2026, 1, 1))

    def _raise(*args, **kwargs):
        raise GoogleCalendarAPIError("timeout")

    broken_client = FakeGoogleCalendarClient(connection)
    broken_client.create_event = _raise
    monkeypatch.setattr(sync, "GoogleCalendarClient", lambda c: broken_client)

    with pytest.raises(GoogleCalendarAPIError):
        sync.sync_connection(connection)

    connection.refresh_from_db()
    assert connection.is_active is True
    assert connection.last_sync_error == "timeout"


@pytest.mark.django_db
def test_inactive_connection_is_skipped(connection, fake_client):
    connection.is_active = False
    connection.save(update_fields=["is_active"])
    Task.objects.create(user=connection.user, title="Renew passport", due_date=date(2026, 1, 1))

    sync.sync_connection(connection)

    assert fake_client == []
