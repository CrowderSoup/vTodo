import pytest
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.tasks.models import Task
from apps.teams.models import Team, TeamMembership
from apps.users.models import User


@pytest.fixture
def api_client_for():
    def _make(user):
        token, _ = Token.objects.get_or_create(user=user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return client

    return _make


@pytest.mark.django_db
def test_task_list_filters_by_team(api_client_for):
    user = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    other_team = Team.objects.create(name="Other")
    TeamMembership.objects.create(team=team, user=user)
    TeamMembership.objects.create(team=other_team, user=user)
    personal_task = Task.objects.create(user=user, title="Personal", status="todo")
    team_task = Task.objects.create(user=user, team=team, title="Team task", status="todo")
    other_team_task = Task.objects.create(user=user, team=other_team, title="Other team task", status="todo")
    client = api_client_for(user)

    response = client.get(reverse("task-list"), {"team": team.pk})

    titles = {t["title"] for t in response.data}
    assert titles == {"Team task"}
    assert "Personal" not in titles
    assert "Other team task" not in titles


@pytest.mark.django_db
def test_assign_action_success(api_client_for):
    user = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user)
    task = Task.objects.create(user=user, team=team, title="Team task", status="todo")
    client = api_client_for(user)

    response = client.post(
        reverse("task-assign", kwargs={"pk": task.pk}), {"assignee_id": user.pk}
    )

    assert response.status_code == 200
    task.refresh_from_db()
    assert task.assignee_id == user.pk


@pytest.mark.django_db
def test_assign_action_rejects_non_member(api_client_for):
    user = User.objects.create_user()
    outsider = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user)
    task = Task.objects.create(user=user, team=team, title="Team task", status="todo")
    client = api_client_for(user)

    response = client.post(
        reverse("task-assign", kwargs={"pk": task.pk}), {"assignee_id": outsider.pk}
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_activity_action_returns_ordered_entries(api_client_for):
    user = User.objects.create_user()
    other = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user)
    TeamMembership.objects.create(team=team, user=other)
    task = Task.objects.create(user=user, team=team, title="Team task", status="todo")
    client = api_client_for(user)

    client.post(reverse("task-assign", kwargs={"pk": task.pk}), {"assignee_id": user.pk})
    client.post(reverse("task-assign", kwargs={"pk": task.pk}), {"assignee_id": other.pk})

    response = client.get(reverse("task-activity", kwargs={"pk": task.pk}))

    assert response.status_code == 200
    assert len(response.data) == 2
    assert response.data[0]["new_value"] == user.username
    assert response.data[1]["new_value"] == other.username


@pytest.mark.django_db
def test_team_list_scoped_to_membership(api_client_for):
    user = User.objects.create_user()
    outsider = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    other_team = Team.objects.create(name="Other")
    TeamMembership.objects.create(team=team, user=user)
    TeamMembership.objects.create(team=other_team, user=outsider)
    client = api_client_for(user)

    response = client.get(reverse("team-list"))

    names = {t["name"] for t in response.data}
    assert names == {"Rocketry"}


@pytest.mark.django_db
def test_status_list_filters_by_team(api_client_for):
    from apps.tasks.models import TaskStatus

    user = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user)
    TaskStatus.objects.create(team=team, name="Review", slug="review")
    client = api_client_for(user)

    response = client.get(reverse("taskstatus-list"), {"team": team.pk})

    slugs = {s["slug"] for s in response.data}
    assert slugs == {"review"}
