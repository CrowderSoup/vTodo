import pytest
from django.urls import reverse

from apps.integrations.models import ExternalLink, SkylightConnection, SkylightMemberMapping
from apps.tasks.models import Task
from apps.teams.models import Team, TeamMembership
from apps.users.models import User


@pytest.fixture
def owner_client(client, db):
    user = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user, role=TeamMembership.ROLE_OWNER)
    client.force_login(user)
    return client, user, team


@pytest.fixture
def member_client(client, db, owner_client):
    _, _, team = owner_client
    user = User.objects.create_user()
    TeamMembership.objects.create(team=team, user=user, role=TeamMembership.ROLE_MEMBER)
    client.force_login(user)
    return client, user, team


@pytest.mark.django_db
def test_settings_teams_page_renders_without_connection(owner_client):
    client, _user, _team = owner_client
    response = client.get(reverse("users:settings-teams"))
    assert response.status_code == 200
    assert b"Connect Skylight" in response.content


@pytest.mark.django_db
def test_connect_view_creates_connection(monkeypatch, owner_client):
    client, _user, team = owner_client
    monkeypatch.setattr(
        "apps.integrations.views.skylight_refresh",
        lambda refresh_token: {"access_token": "tok123", "refresh_token": "rotated-tok"},
    )

    response = client.post(
        reverse("integrations:skylight-connect", args=[team.pk]),
        {"refresh_token": "initial-refresh-tok", "frame_id": "frame123"},
    )

    assert response.status_code == 302
    connection = SkylightConnection.objects.get(team=team)
    assert connection.get_token() == "tok123"
    assert connection.get_refresh_token() == "rotated-tok"
    assert not connection.is_ready
    assert response.url == reverse("integrations:skylight-select-calendar", args=[team.pk])


@pytest.mark.django_db
def test_connect_view_rejects_non_owner(monkeypatch, member_client):
    client, _user, team = member_client
    monkeypatch.setattr(
        "apps.integrations.views.skylight_refresh",
        lambda refresh_token: {"access_token": "tok123", "refresh_token": "rotated-tok"},
    )

    response = client.post(
        reverse("integrations:skylight-connect", args=[team.pk]),
        {"refresh_token": "initial-refresh-tok", "frame_id": "frame123"},
    )

    assert response.status_code == 404
    assert not SkylightConnection.objects.filter(team=team).exists()


@pytest.mark.django_db
def test_connect_view_shows_distinct_error_for_rejected_refresh_token(monkeypatch, owner_client):
    client, _user, team = owner_client
    from apps.integrations.skylight.client import SkylightAuthError

    def _raise(refresh_token):
        raise SkylightAuthError("Skylight rejected the refresh token: 400")

    monkeypatch.setattr("apps.integrations.views.skylight_refresh", _raise)

    response = client.post(
        reverse("integrations:skylight-connect", args=[team.pk]),
        {"refresh_token": "bad-tok", "frame_id": "frame123"},
        follow=True,
    )

    assert response.status_code == 200
    messages = [str(m) for m in response.context["messages"]]
    assert any("rejected that refresh token" in m for m in messages)
    assert not SkylightConnection.objects.filter(team=team).exists()


@pytest.mark.django_db
def test_select_calendar_view_get_lists_calendars(monkeypatch, owner_client):
    client, _user, team = owner_client
    connection = SkylightConnection(team=team, frame_id="frame123")
    connection.set_refresh_token("initial-refresh-tok")
    connection.set_token("tok123")
    connection.save()

    monkeypatch.setattr(
        "apps.integrations.views.SkylightClient.list_source_calendars",
        lambda self: [{"id": "cal-1", "attributes": {"email": "owner@gmail.com"}}],
    )

    response = client.get(reverse("integrations:skylight-select-calendar", args=[team.pk]))

    assert response.status_code == 200
    assert b"owner@gmail.com" in response.content


@pytest.mark.django_db
def test_select_calendar_view_post_saves_choice(owner_client):
    client, _user, team = owner_client
    connection = SkylightConnection(team=team, frame_id="frame123")
    connection.set_refresh_token("initial-refresh-tok")
    connection.set_token("tok123")
    connection.save()

    response = client.post(
        reverse("integrations:skylight-select-calendar", args=[team.pk]),
        {"calendar_account_id": "cal-1", "calendar_label": "owner@gmail.com"},
    )

    assert response.status_code == 302
    connection.refresh_from_db()
    assert connection.calendar_account_id == "cal-1"
    assert connection.is_ready


@pytest.mark.django_db
def test_mapping_view_saves_assignments(monkeypatch, owner_client):
    client, _owner, team = owner_client
    member = User.objects.create_user()
    TeamMembership.objects.create(team=team, user=member, role=TeamMembership.ROLE_MEMBER)

    connection = SkylightConnection(
        team=team, frame_id="frame123",
        calendar_account_id="cal-1", calendar_id="owner@gmail.com",
    )
    connection.set_refresh_token("initial-refresh-tok")
    connection.set_token("tok123")
    connection.save()

    monkeypatch.setattr(
        "apps.integrations.views.SkylightClient.list_categories",
        lambda self: [{"id": "cat-1", "attributes": {"label": "Garrett"}}],
    )

    response = client.post(
        reverse("integrations:skylight-mapping", args=[team.pk]),
        {f"category_label:cat-1": "Garrett", f"user:cat-1": str(member.pk)},
    )

    assert response.status_code == 302
    mapping = SkylightMemberMapping.objects.get(connection=connection, category_id="cat-1")
    assert mapping.user_id == member.pk


@pytest.mark.django_db
def test_mapping_view_ignores_user_id_outside_team(monkeypatch, owner_client):
    client, _owner, team = owner_client
    outsider = User.objects.create_user()

    connection = SkylightConnection(
        team=team, frame_id="frame123",
        calendar_account_id="cal-1", calendar_id="owner@gmail.com",
    )
    connection.set_refresh_token("initial-refresh-tok")
    connection.set_token("tok123")
    connection.save()

    monkeypatch.setattr(
        "apps.integrations.views.SkylightClient.list_categories",
        lambda self: [{"id": "cat-1", "attributes": {"label": "Garrett"}}],
    )

    response = client.post(
        reverse("integrations:skylight-mapping", args=[team.pk]),
        {f"category_label:cat-1": "Garrett", f"user:cat-1": str(outsider.pk)},
    )

    assert response.status_code == 302
    mapping = SkylightMemberMapping.objects.get(connection=connection, category_id="cat-1")
    assert mapping.user_id is None


@pytest.mark.django_db
def test_disconnect_view_removes_connection_and_links(owner_client):
    client, owner, team = owner_client
    connection = SkylightConnection(
        team=team, frame_id="frame123",
        calendar_account_id="cal-1", calendar_id="owner@gmail.com",
    )
    connection.set_refresh_token("initial-refresh-tok")
    connection.save()
    task = Task.objects.create(user=owner, team=team, title="Synced task")
    ExternalLink.objects.create(task=task, provider=ExternalLink.Provider.SKYLIGHT, external_id="evt-1")

    response = client.post(reverse("integrations:skylight-disconnect", args=[team.pk]))

    assert response.status_code == 302
    assert not SkylightConnection.objects.filter(team=team).exists()
    assert not ExternalLink.objects.filter(task=task).exists()
