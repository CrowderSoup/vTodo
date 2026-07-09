import pytest
from django.urls import reverse

from apps.users.models import User


@pytest.fixture
def logged_in_client(client, db):
    user = User.objects.create_user()
    client.force_login(user)
    return client, user


@pytest.mark.django_db
def test_settings_post_saves_default_status(logged_in_client):
    client, user = logged_in_client
    default_status = user.task_statuses.get(slug="done")

    response = client.post(
        reverse("users:settings"),
        {
            "display_name": "",
            "avatar_url": "",
            "default_status": str(default_status.pk),
        },
    )

    user.refresh_from_db()
    assert response.status_code == 302
    assert user.default_status_id == default_status.pk


@pytest.mark.django_db
def test_settings_post_rejects_default_status_from_another_user(logged_in_client):
    client, user = logged_in_client
    other_user = User.objects.create_user()
    other_status = other_user.task_statuses.first()

    response = client.post(
        reverse("users:settings"),
        {
            "display_name": "",
            "avatar_url": "",
            "default_status": str(other_status.pk),
        },
    )

    user.refresh_from_db()
    assert response.status_code == 302
    assert user.default_status_id is None


@pytest.mark.django_db
def test_settings_includes_shared_confirm_modal(logged_in_client):
    client, _ = logged_in_client
    response = client.get(reverse("users:settings"))
    content = response.content.decode()

    assert response.status_code == 200
    assert 'id="confirm-modal"' in content
    assert 'id="confirm-modal-cancel"' in content


# ---------------------------------------------------------------------------
# SettingsTeamsView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_settings_teams_lists_owned_team_with_pending_invite(logged_in_client):
    from apps.teams.models import Team, TeamInvite, TeamMembership

    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user, role=TeamMembership.ROLE_OWNER)
    TeamInvite.generate(team, "a@example.com", user)

    response = client.get(reverse("users:settings-teams"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Rocketry" in content
    assert "a@example.com" in content


@pytest.mark.django_db
def test_settings_teams_empty_state_for_no_teams(logged_in_client):
    client, _ = logged_in_client
    response = client.get(reverse("users:settings-teams"))
    assert response.status_code == 200
    assert b"not on any teams yet" in response.content


# ---------------------------------------------------------------------------
# Team-scoped column/status creation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_column_create_with_team_scope(logged_in_client):
    from apps.teams.models import Team, TeamMembership

    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user, role=TeamMembership.ROLE_OWNER)

    response = client.post(
        reverse("users:column-create"),
        {"label": "Team Lane", "team": team.pk, "assignee": "unassigned"},
    )

    assert response.status_code == 200
    from apps.boards.models import Column

    column = Column.objects.get(label="Team Lane")
    assert column.filter_config["scope"] == f"team:{team.pk}"
    assert column.filter_config["assignee"] == "unassigned"


@pytest.mark.django_db
def test_column_create_response_shows_team_name_not_raw_scope(logged_in_client):
    from apps.teams.models import Team, TeamMembership

    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user, role=TeamMembership.ROLE_OWNER)

    response = client.post(
        reverse("users:column-create"),
        {"label": "Team Lane", "team": team.pk},
    )

    content = response.content.decode()
    assert "Rocketry" in content
    assert f"team:{team.pk}" not in content


@pytest.mark.django_db
def test_column_create_rejects_non_member_team(logged_in_client):
    from apps.teams.models import Team

    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")

    response = client.post(reverse("users:column-create"), {"label": "Team Lane", "team": team.pk})

    assert response.status_code == 422


@pytest.mark.django_db
def test_status_create_with_team_scope(logged_in_client):
    from apps.tasks.models import TaskStatus
    from apps.teams.models import Team, TeamMembership

    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user, role=TeamMembership.ROLE_MEMBER)

    response = client.post(reverse("users:status-create"), {"name": "Review", "team": team.pk})

    assert response.status_code == 200
    assert TaskStatus.objects.filter(team=team, slug="review").exists()


@pytest.mark.django_db
def test_status_create_rejects_non_member_team(logged_in_client):
    from apps.teams.models import Team

    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")

    response = client.post(reverse("users:status-create"), {"name": "Review", "team": team.pk})

    assert response.status_code == 422
