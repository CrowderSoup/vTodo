import pytest
from datetime import date, time

from apps.tasks.models import Task
from apps.teams.models import Team, TeamMembership
from apps.users.models import User


@pytest.mark.django_db
def test_task_default_status_is_todo():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="My task")
    assert task.status == "todo"


@pytest.mark.django_db
def test_task_str():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Do the thing")
    assert str(task) == "Do the thing"


@pytest.mark.django_db
def test_task_status_transition():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Move me")
    task.status = "in_progress"
    task.save()
    task.refresh_from_db()
    assert task.status == "in_progress"


@pytest.mark.django_db
def test_task_completed_at_is_nullable():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Not done yet")
    assert task.completed_at is None


@pytest.mark.django_db
def test_task_tags_default_empty_list():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Tagged task")
    assert task.tags == []


@pytest.mark.django_db
def test_spawn_recurrence_keeps_team_task_on_the_team():
    user = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user)
    task = Task.objects.create(
        user=user, team=team, title="Weekly sync", recurrence_days=7,
    )

    spawned = task.spawn_recurrence(completion_date=date(2026, 1, 1))

    assert spawned.team_id == team.pk


@pytest.mark.django_db
def test_due_time_and_duration_default_to_none():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="No specific time", due_date=date(2026, 1, 1))
    assert task.due_time is None
    assert task.duration_minutes is None


@pytest.mark.django_db
def test_spawn_recurrence_carries_over_due_time_and_duration():
    user = User.objects.create_user()
    task = Task.objects.create(
        user=user, title="Standup", recurrence_days=1,
        due_date=date(2026, 1, 1), due_time=time(9, 30), duration_minutes=15,
    )

    spawned = task.spawn_recurrence(completion_date=date(2026, 1, 1))

    assert spawned.due_time == time(9, 30)
    assert spawned.duration_minutes == 15
