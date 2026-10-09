from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from apps.tasks.models import Task, TaskStatus
from apps.tasks.selectors import (
    get_task_or_404,
    known_tags_for_board,
    move_task,
    resolve_status_for_task,
    visible_statuses_qs,
    visible_tasks_qs,
)
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
def test_visible_statuses_qs_scoped_to_user():
    user = User.objects.create_user()
    other = User.objects.create_user()
    personal_statuses = list(TaskStatus.objects.filter(user=user))
    assert list(visible_statuses_qs(user)) == personal_statuses
    assert list(visible_statuses_qs(other)) != personal_statuses


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


@pytest.mark.django_db
def test_completing_an_earlier_occurrence_does_not_spawn_while_one_is_open():
    """Completing an earlier occurrence must not open a second copy while one
    is still open.

    Production: "Mobility / stretching session" task 166 stayed backlog,
    never completed, and not archived, while task 171 was created due the
    next day. The next copy is created only once no open copy remains.
    """
    user = User.objects.create_user()
    earlier = Task.objects.create(
        user=user,
        title="Mobility / stretching session",
        status="todo",
        due_date=date(2026, 10, 8),
        tags=["fitness", "health", "personal"],
        recurrence_days=1,
        recurrence_from=Task.RECURRENCE_FROM_COMPLETION,
    )
    current = Task.objects.create(
        user=user,
        title="Mobility / stretching session",
        status="backlog",
        due_date=date(2026, 10, 9),
        tags=["fitness", "health", "personal"],
        recurrence_days=1,
        recurrence_from=Task.RECURRENCE_FROM_COMPLETION,
    )

    move_task(user, earlier, "done")

    earlier.refresh_from_db()
    current.refresh_from_db()
    assert earlier.completed_at is not None
    assert current.status == "backlog"
    assert current.completed_at is None
    assert Task.objects.filter(
        user=user,
        title="Mobility / stretching session",
        completed_at__isnull=True,
        is_archived=False,
    ).count() == 1

    # Completing the open copy is what should roll the series forward.
    move_task(user, current, "done")
    successor = Task.objects.get(
        user=user,
        title="Mobility / stretching session",
        completed_at__isnull=True,
        is_archived=False,
    )
    assert successor.status == "backlog"
    assert successor.due_date == timezone.localdate() + timedelta(days=1)
    assert successor.recurrence_days == 1
    assert successor.recurrence_from == Task.RECURRENCE_FROM_COMPLETION


@pytest.mark.django_db
def test_known_tags_for_board_returns_sorted_distinct_tags():
    from apps.boards.models import Board

    user = User.objects.create_user()
    board = Board.objects.get(user=user)
    Task.objects.create(user=user, title="A", tags=["work", "urgent"])
    Task.objects.create(user=user, title="B", tags=["urgent", "design"])
    Task.objects.create(user=user, title="C", tags=[])

    assert known_tags_for_board(board) == ["design", "urgent", "work"]


@pytest.mark.django_db
def test_known_tags_for_board_scoped_to_board_owner():
    from apps.boards.models import Board

    user = User.objects.create_user()
    other = User.objects.create_user()
    board = Board.objects.get(user=user)
    Task.objects.create(user=user, title="Mine", tags=["mine"])
    Task.objects.create(user=other, title="Theirs", tags=["theirs"])

    assert known_tags_for_board(board) == ["mine"]
