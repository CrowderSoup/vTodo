import importlib
from datetime import timedelta

import pytest
from django.apps import apps as django_apps
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.tasks import lifecycle
from apps.tasks.models import ClaimState, Task, TaskState, TaskStatus
from apps.tasks.selectors import move_task
from apps.users.models import User


def _api(user):
    token, _ = Token.objects.get_or_create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return client


@pytest.mark.django_db
def test_state_follows_completion_and_archiving():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="T")
    assert task.state == TaskState.OPEN

    move_task(user, task, "done")
    assert task.state == TaskState.DONE

    task.is_archived = True
    assert task.state == TaskState.ARCHIVED
    task.is_archived = False
    assert task.state == TaskState.DONE

    move_task(user, task, "todo")
    assert task.state == TaskState.OPEN


@pytest.mark.django_db
def test_in_state_matches_state():
    user = User.objects.create_user()
    open_task = Task.objects.create(user=user, title="Open")
    done = Task.objects.create(user=user, title="Done")
    move_task(user, done, "done")
    archived = Task.objects.create(user=user, title="Archived", is_archived=True)

    for task in (open_task, done, archived):
        assert list(Task.objects.in_state(task.state)) == [task]


@pytest.mark.parametrize(
    ("was_done", "to_done", "expected"),
    [
        (False, True, lifecycle.Transition.COMPLETE),
        (True, False, lifecycle.Transition.REOPEN),
        (False, False, lifecycle.Transition.STAY),
        (True, True, lifecycle.Transition.STAY),
    ],
)
def test_transition_for(was_done, to_done, expected):
    task = Task(completed_at=timezone.now() if was_done else None)
    assert lifecycle.transition_for(task, to_done=to_done) is expected


@pytest.mark.django_db
def test_claim_state():
    user = User.objects.create_user()
    now = timezone.now()
    task = Task(user=user, title="T")
    assert task.claim_state(now) == ClaimState.UNCLAIMED

    task.claimed_by = user
    task.claim_expires_at = now + timedelta(minutes=1)
    assert task.claim_state(now) == ClaimState.HELD
    assert task.claim_state(now + timedelta(minutes=2)) == ClaimState.LAPSED


@pytest.mark.django_db
def test_api_create_into_done_status_starts_done():
    user = User.objects.create_user()

    response = _api(user).post(reverse("task-list"), {"title": "Already done", "status": "done"}, format="json")

    task = Task.objects.get(pk=response.data["id"])
    assert task.state == TaskState.DONE
    assert task.previous_status == ""


@pytest.mark.django_db
def test_web_create_into_done_status_starts_done(client):
    user = User.objects.create_user()
    client.force_login(user)

    client.post(reverse("boards:task-create"), {"title": "Already done", "status": "done"})

    assert Task.objects.get(title="Already done").state == TaskState.DONE


@pytest.mark.django_db
def test_create_into_open_status_starts_open():
    user = User.objects.create_user()

    response = _api(user).post(reverse("task-list"), {"title": "Fresh", "status": "todo"}, format="json")

    assert Task.objects.get(pk=response.data["id"]).state == TaskState.OPEN


@pytest.mark.django_db
def test_flipping_a_status_to_done_completes_its_tasks():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Waiting", status="in_progress", claimed_by=user,
                               claim_expires_at=timezone.now() + timedelta(minutes=5))
    other = Task.objects.create(user=user, title="Elsewhere", status="todo")

    _api(user).patch(reverse("taskstatus-detail", args=["in_progress"]), {"is_done": True}, format="json")

    task.refresh_from_db()
    other.refresh_from_db()
    assert task.state == TaskState.DONE
    assert task.claimed_by is None
    assert other.state == TaskState.OPEN


@pytest.mark.django_db
def test_flipping_a_status_from_done_reopens_its_tasks():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Finished")
    move_task(user, task, "done")

    _api(user).patch(reverse("taskstatus-detail", args=["done"]), {"is_done": False}, format="json")

    task.refresh_from_db()
    assert task.state == TaskState.OPEN
    assert task.previous_status == ""
    assert not Task.objects.exclude(pk=task.pk).exists()  # no recurrence or copies


@pytest.mark.django_db
def test_migration_brings_completion_in_line_with_status():
    migration = importlib.import_module("apps.tasks.migrations.0015_task_completion_follows_status")
    user = User.objects.create_user()
    in_done = Task.objects.create(user=user, title="In done, never moved", status="done")
    stale = Task.objects.create(user=user, title="Reopened by hand", status="todo",
                                completed_at=timezone.now(), previous_status="in_progress")
    fine = Task.objects.create(user=user, title="Fine", status="todo")

    migration.forwards(django_apps, None)

    for task in (in_done, stale, fine):
        task.refresh_from_db()
    assert in_done.completed_at == in_done.updated_at
    assert (stale.completed_at, stale.previous_status) == (None, "")
    assert fine.completed_at is None
    assert TaskStatus.objects.filter(slug="done", is_done=True).exists()
