import datetime

import pytest
from django.utils import timezone

from apps.integrations.models import ExternalLink, SkylightConnection, SkylightMemberMapping
from apps.integrations.skylight.sync import sync_connection
from apps.tasks.models import Task
from apps.teams.models import Team, TeamMembership
from apps.users.models import User


class FakeSkylightClient:
    """Stands in for SkylightClient in tests -- an in-memory calendar keyed by
    fake event id, so sync_connection can be exercised without any HTTP."""

    def __init__(self, connection):
        self.connection = connection
        self.events = {}
        self.created = []
        self.updated = []
        self.deleted = []
        self._next_id = 1

    def _make_event(self, event_id, payload):
        return {
            "id": event_id,
            "attributes": {
                "summary": payload["summary"],
                "description": payload.get("description", ""),
                "all_day": payload.get("all_day", False),
                "starts_at": payload["starts_at"],
                "ends_at": payload["ends_at"],
            },
            "relationships": {
                "categories": {
                    "data": [{"id": cid, "type": "category"} for cid in payload.get("category_ids", [])]
                }
            },
        }

    def seed_event(self, event_id, **attrs):
        payload = {
            "summary": attrs.get("summary", ""),
            "description": attrs.get("description", ""),
            "all_day": attrs.get("all_day", False),
            "starts_at": attrs.get("starts_at", "2026-07-25T00:00:00+00:00"),
            "ends_at": attrs.get("ends_at", "2026-07-25T00:00:00+00:00"),
            "category_ids": attrs.get("category_ids", []),
        }
        self.events[event_id] = self._make_event(event_id, payload)

    def list_calendar_events(self, date_min, date_max, timezone_name="UTC"):
        return list(self.events.values())

    def create_calendar_event(self, payload):
        event_id = f"evt-{self._next_id}"
        self._next_id += 1
        self.created.append(payload)
        event = self._make_event(event_id, payload)
        self.events[event_id] = event
        return event

    def update_calendar_event(self, event_id, payload):
        self.updated.append((event_id, payload))
        event = self._make_event(event_id, payload)
        self.events[event_id] = event
        return event

    def delete_calendar_event(self, event_id):
        self.deleted.append(event_id)
        self.events.pop(event_id, None)


@pytest.fixture
def owner(db):
    return User.objects.create_user()


@pytest.fixture
def team(db):
    return Team.objects.create(name="Rocketry")


@pytest.fixture
def connection(db, team, owner):
    conn = SkylightConnection(
        team=team,
        frame_id="frame123",
        email="owner@example.com",
        calendar_account_id="cal-1",
        calendar_id="owner@gmail.com",
        connected_by=owner,
    )
    conn.set_password("hunter2")
    conn.save()
    return conn


@pytest.fixture
def fake_client(monkeypatch, connection):
    fake = FakeSkylightClient(connection)
    monkeypatch.setattr("apps.integrations.skylight.sync.SkylightClient", lambda conn: fake)
    return fake


def _make_task(team, owner, **kwargs):
    kwargs.setdefault("due_date", datetime.date(2026, 7, 25))
    return Task.objects.create(user=owner, team=team, title="Take out trash", **kwargs)


@pytest.mark.django_db
def test_sync_pushes_new_eligible_task(team, owner, connection, fake_client):
    task = _make_task(team, owner)

    sync_connection(connection)

    assert len(fake_client.created) == 1
    link = ExternalLink.objects.get(task=task, provider=ExternalLink.Provider.SKYLIGHT)
    assert link.external_id in fake_client.events


@pytest.mark.django_db
def test_sync_does_not_push_tasks_without_due_date(team, owner, connection, fake_client):
    Task.objects.create(user=owner, team=team, title="Someday maybe", due_date=None)

    sync_connection(connection)

    assert fake_client.created == []
    assert not ExternalLink.objects.filter(provider=ExternalLink.Provider.SKYLIGHT).exists()


@pytest.mark.django_db
def test_sync_pushes_local_change_when_only_local_changed(team, owner, connection, fake_client):
    task = _make_task(team, owner)
    sync_connection(connection)  # initial push, creates the link
    link = ExternalLink.objects.get(task=task, provider=ExternalLink.Provider.SKYLIGHT)

    task.title = "Take out recycling"
    task.save(update_fields=["title", "updated_at"])

    sync_connection(connection)

    assert len(fake_client.updated) == 1
    _event_id, payload = fake_client.updated[0]
    assert payload["summary"] == "Take out recycling"


@pytest.mark.django_db
def test_sync_pulls_remote_change_when_only_remote_changed(team, owner, connection, fake_client):
    task = _make_task(team, owner)
    sync_connection(connection)
    link = ExternalLink.objects.get(task=task, provider=ExternalLink.Provider.SKYLIGHT)

    # Simulate someone editing the event directly on the Skylight touchscreen.
    fake_client.events[link.external_id]["attributes"]["summary"] = "Take out ALL the trash"

    sync_connection(connection)

    task.refresh_from_db()
    assert task.title == "Take out ALL the trash"


@pytest.mark.django_db
def test_sync_local_wins_when_both_sides_changed(team, owner, connection, fake_client):
    task = _make_task(team, owner)
    sync_connection(connection)
    link = ExternalLink.objects.get(task=task, provider=ExternalLink.Provider.SKYLIGHT)

    # Force "both changed since last sync": push synced_at into the past, then
    # touch both the local task and the remote event.
    link.synced_at = timezone.now() - datetime.timedelta(hours=1)
    link.save(update_fields=["synced_at"])
    task.title = "Local wins this one"
    task.save(update_fields=["title", "updated_at"])
    fake_client.events[link.external_id]["attributes"]["summary"] = "Remote edit"

    sync_connection(connection)

    task.refresh_from_db()
    assert task.title == "Local wins this one"
    assert len(fake_client.updated) == 1


@pytest.mark.django_db
def test_sync_pulls_remote_change_when_local_touch_was_sync_irrelevant(team, owner, connection, fake_client):
    task = _make_task(team, owner)
    sync_connection(connection)
    link = ExternalLink.objects.get(task=task, provider=ExternalLink.Provider.SKYLIGHT)

    # Touch the task in a way that bumps updated_at but doesn't change anything
    # that gets synced to Skylight (e.g. reordering on the board).
    task.order = 5
    task.save(update_fields=["order", "updated_at"])
    fake_client.events[link.external_id]["attributes"]["summary"] = "Take out ALL the trash"

    sync_connection(connection)

    task.refresh_from_db()
    assert task.title == "Take out ALL the trash"
    assert fake_client.updated == []


@pytest.mark.django_db
def test_sync_removes_event_when_task_no_longer_eligible(team, owner, connection, fake_client):
    task = _make_task(team, owner)
    sync_connection(connection)
    link = ExternalLink.objects.get(task=task, provider=ExternalLink.Provider.SKYLIGHT)
    event_id = link.external_id

    task.completed_at = timezone.now()
    task.save(update_fields=["completed_at"])

    sync_connection(connection)

    assert event_id in fake_client.deleted
    assert not ExternalLink.objects.filter(task=task).exists()


@pytest.mark.django_db
def test_sync_pushes_category_id_for_mapped_assignee(team, owner, connection, fake_client):
    member = User.objects.create_user()
    TeamMembership.objects.create(team=team, user=member, role=TeamMembership.ROLE_MEMBER)
    SkylightMemberMapping.objects.create(connection=connection, category_id="cat-1", user=member)
    task = _make_task(team, owner, assignee=member)

    sync_connection(connection)

    assert fake_client.created[0]["category_ids"] == ["cat-1"]


@pytest.mark.django_db
def test_sync_pull_leaves_task_unassigned_when_category_unmapped(team, owner, connection, fake_client):
    member = User.objects.create_user()
    TeamMembership.objects.create(team=team, user=member, role=TeamMembership.ROLE_MEMBER)
    task = _make_task(team, owner, assignee=member)
    sync_connection(connection)
    link = ExternalLink.objects.get(task=task, provider=ExternalLink.Provider.SKYLIGHT)

    # Remote event now references a category with no mapping at all.
    fake_client.events[link.external_id]["relationships"]["categories"]["data"] = [
        {"id": "some-unmapped-category", "type": "category"}
    ]

    sync_connection(connection)

    task.refresh_from_db()
    assert task.assignee_id is None


@pytest.mark.django_db
def test_sync_pull_reassigns_task_from_mapped_category(team, owner, connection, fake_client):
    member = User.objects.create_user()
    TeamMembership.objects.create(team=team, user=member, role=TeamMembership.ROLE_MEMBER)
    SkylightMemberMapping.objects.create(connection=connection, category_id="cat-1", user=member)
    task = _make_task(team, owner)
    sync_connection(connection)
    link = ExternalLink.objects.get(task=task, provider=ExternalLink.Provider.SKYLIGHT)

    fake_client.events[link.external_id]["relationships"]["categories"]["data"] = [
        {"id": "cat-1", "type": "category"}
    ]

    sync_connection(connection)

    task.refresh_from_db()
    assert task.assignee_id == member.id
