from datetime import date, datetime, timezone as dt_timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from apps.tasks.models import Task, TaskStatus
from apps.tasks.selectors import (
    AssignmentError,
    assign_task,
    get_task_or_404,
    grouped_visible_statuses,
    move_task,
    resolve_status_for_task,
    visible_statuses_qs,
    visible_tasks_qs,
)
from apps.teams.models import Team, TeamMembership
from apps.users.models import User
from django.http import Http404
from django.utils import timezone


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


@pytest.mark.django_db
def test_grouped_visible_statuses_always_includes_personal_group_first():
    user = User.objects.create_user()

    groups = grouped_visible_statuses(user)

    assert groups[0]["label"] == "Personal"
    assert groups[0]["team_id"] is None
    assert [s.slug for s in groups[0]["statuses"]] == ["backlog", "todo", "in_progress", "done"]


@pytest.mark.django_db
def test_grouped_visible_statuses_includes_teams_with_statuses():
    user = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user)
    TaskStatus.objects.create(team=team, name="Shipped", slug="shipped", order=0)

    groups = grouped_visible_statuses(user)

    assert [g["label"] for g in groups] == ["Personal", "Rocketry"]
    assert groups[1]["team_id"] == team.pk
    assert [s.slug for s in groups[1]["statuses"]] == ["shipped"]


@pytest.mark.django_db
def test_grouped_visible_statuses_omits_teams_with_no_statuses():
    """A team the user belongs to but that has had all its statuses deleted doesn't
    show up as an empty group."""
    user = User.objects.create_user()
    team = Team.objects.create(name="Empty Team")
    TeamMembership.objects.create(team=team, user=user)

    groups = grouped_visible_statuses(user)

    assert [g["label"] for g in groups] == ["Personal"]


@pytest.mark.django_db
def test_move_task_spawns_recurrence_from_users_local_completion_date():
    """completed_at is stamped in UTC; the recurrence must be based on the
    user's local calendar date, not the UTC date, which can already be a day
    ahead in the evening in a UTC-negative zone."""
    user = User.objects.create_user(timezone="America/Chicago")
    task = Task.objects.create(
        user=user, title="Nightly check", status="todo", recurrence_days=1,
    )

    # 9pm on Jan 1 in America/Chicago (UTC-6) is already Jan 2 in UTC.
    completed_at_utc = datetime(2026, 1, 2, 3, 0, tzinfo=dt_timezone.utc)
    with timezone.override(ZoneInfo("America/Chicago")):
        with patch("apps.tasks.selectors.timezone.now", return_value=completed_at_utc):
            move_task(user, task, "done")

    spawned = Task.objects.get(title="Nightly check", status="backlog")
    assert spawned.due_date == date(2026, 1, 2)
