import pytest

from apps.tasks.models import Task, TaskStatus
from apps.tasks.selectors import (
    AssignmentError,
    assign_task,
    get_task_or_404,
    resolve_status_for_task,
    visible_statuses_qs,
    visible_tasks_qs,
)
from apps.teams.models import Team, TeamMembership
from apps.users.models import User
from django.http import Http404


@pytest.mark.django_db
def test_visible_tasks_includes_own_personal_task():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Mine")
    assert task in visible_tasks_qs(user)


@pytest.mark.django_db
def test_visible_tasks_excludes_another_users_personal_task():
    user = User.objects.create_user()
    other = User.objects.create_user()
    task = Task.objects.create(user=other, title="Not yours")
    assert task not in visible_tasks_qs(user)


@pytest.mark.django_db
def test_visible_tasks_includes_teammates_team_task():
    team = Team.objects.create(name="Rocketry")
    creator = User.objects.create_user()
    viewer = User.objects.create_user()
    TeamMembership.objects.create(team=team, user=creator)
    TeamMembership.objects.create(team=team, user=viewer)
    task = Task.objects.create(user=creator, team=team, title="Team task")
    assert task in visible_tasks_qs(viewer)


@pytest.mark.django_db
def test_visible_tasks_excludes_other_teams_task():
    team = Team.objects.create(name="Rocketry")
    other_team = Team.objects.create(name="Other")
    creator = User.objects.create_user()
    outsider = User.objects.create_user()
    TeamMembership.objects.create(team=team, user=creator)
    TeamMembership.objects.create(team=other_team, user=outsider)
    task = Task.objects.create(user=creator, team=team, title="Team task")
    assert task not in visible_tasks_qs(outsider)


@pytest.mark.django_db
def test_get_task_or_404_raises_for_invisible_task():
    user = User.objects.create_user()
    other = User.objects.create_user()
    task = Task.objects.create(user=other, title="Not yours")
    with pytest.raises(Http404):
        get_task_or_404(user, task.pk)


@pytest.mark.django_db
def test_resolve_status_for_task_personal():
    user = User.objects.create_user()
    status = TaskStatus.objects.get(user=user, slug="todo")
    task = Task.objects.create(user=user, title="Mine", status="todo")
    assert resolve_status_for_task(task) == status


@pytest.mark.django_db
def test_resolve_status_for_task_team():
    team = Team.objects.create(name="Rocketry")
    creator = User.objects.create_user()
    status = TaskStatus.objects.create(team=team, name="Todo", slug="todo")
    task = Task.objects.create(user=creator, team=team, title="Team task", status="todo")
    assert resolve_status_for_task(task) == status


@pytest.mark.django_db
def test_visible_statuses_qs_team_scope():
    team = Team.objects.create(name="Rocketry")
    user = User.objects.create_user()
    personal_statuses = list(TaskStatus.objects.filter(user=user))
    team_status = TaskStatus.objects.create(team=team, name="Todo", slug="todo")
    assert list(visible_statuses_qs(user)) == personal_statuses
    assert list(visible_statuses_qs(user, team=team)) == [team_status]


@pytest.mark.django_db
def test_assign_task_rejects_personal_task():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Mine")
    with pytest.raises(AssignmentError):
        assign_task(user, task, user)


@pytest.mark.django_db
def test_assign_task_rejects_non_member_assignee():
    team = Team.objects.create(name="Rocketry")
    creator = User.objects.create_user()
    outsider = User.objects.create_user()
    TeamMembership.objects.create(team=team, user=creator)
    task = Task.objects.create(user=creator, team=team, title="Team task")
    with pytest.raises(AssignmentError):
        assign_task(creator, task, outsider)


@pytest.mark.django_db
def test_assign_task_success_creates_activity_entry():
    team = Team.objects.create(name="Rocketry")
    creator = User.objects.create_user()
    assignee = User.objects.create_user()
    TeamMembership.objects.create(team=team, user=creator)
    TeamMembership.objects.create(team=team, user=assignee)
    task = Task.objects.create(user=creator, team=team, title="Team task")

    assign_task(creator, task, assignee)
    task.refresh_from_db()

    assert task.assignee_id == assignee.id
    assert task.activity.count() == 1
    entry = task.activity.first()
    assert entry.field == "assignee"
    assert entry.old_value == "Unassigned"
    assert entry.new_value == assignee.username


@pytest.mark.django_db
def test_assign_task_reassignment_accumulates_activity():
    team = Team.objects.create(name="Rocketry")
    creator = User.objects.create_user()
    first_assignee = User.objects.create_user()
    second_assignee = User.objects.create_user()
    for u in (creator, first_assignee, second_assignee):
        TeamMembership.objects.create(team=team, user=u)
    task = Task.objects.create(user=creator, team=team, title="Team task")

    assign_task(creator, task, first_assignee)
    assign_task(creator, task, second_assignee)

    assert task.activity.count() == 2
