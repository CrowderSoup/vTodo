from datetime import date

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.boards.models import Board
from apps.tasks.models import Task, TaskActivity, TaskComment
from apps.users.models import User


@pytest.fixture
def logged_in(client, db):
    user = User.objects.create_user(display_name="Aaron")
    client.force_login(user)
    return client, user


def _actions(task_pk):
    return [(r.action, r.field, r.source) for r in TaskActivity.objects.filter(task_pk=task_pk).order_by("pk")]


@pytest.mark.django_db
def test_board_create_records_created(logged_in):
    client, user = logged_in
    client.post(reverse("boards:task-create"), {"title": "New", "status": "todo"})
    task = Task.objects.get(title="New")
    assert _actions(task.pk) == [("created", "", "web")]
    assert TaskActivity.objects.get(task_pk=task.pk).actor == user


@pytest.mark.django_db
def test_panel_create_records_created(logged_in):
    client, _ = logged_in
    client.post(reverse("boards:task-panel-create"), {"title": "From panel"})
    task = Task.objects.get(title="From panel")
    assert _actions(task.pk) == [("created", "", "web")]


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", ["boards:task-update", "boards:task-panel-update"])
def test_updates_record_changed_fields_only(logged_in, url_name):
    client, user = logged_in
    task = Task.objects.create(user=user, title="Old", status="todo")
    client.post(reverse(url_name, args=[task.pk]), {
        "title": "New", "notes": "", "due_date": "2026-12-01", "tags": "",
        "recurrence_from": Task.RECURRENCE_FROM_COMPLETION,
    })
    assert sorted(f for _, f, _ in _actions(task.pk)) == ["due_date", "title"]


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", ["boards:task-update", "boards:task-panel-update"])
def test_resaving_a_dated_task_records_nothing(logged_in, url_name):
    client, user = logged_in
    task = Task.objects.create(user=user, title="Same", status="todo", due_date=date(2026, 12, 1))
    client.post(reverse(url_name, args=[task.pk]), {
        "title": "Same", "notes": "", "due_date": "2026-12-01", "tags": "",
        "recurrence_from": Task.RECURRENCE_FROM_COMPLETION,
    })
    assert _actions(task.pk) == []


@pytest.mark.django_db
def test_update_is_rolled_back_when_logging_fails(logged_in, monkeypatch):
    from apps.tasks import activity

    def boom(*args, **kwargs):
        raise RuntimeError("log write failed")

    monkeypatch.setattr(activity, "record_changes", boom)
    client, user = logged_in
    task = Task.objects.create(user=user, title="Old", status="todo")
    with pytest.raises(RuntimeError):
        client.post(reverse("boards:task-panel-update", args=[task.pk]), {
            "title": "New", "notes": "", "due_date": "", "tags": "",
            "recurrence_from": Task.RECURRENCE_FROM_COMPLETION,
        })
    task.refresh_from_db()
    assert task.title == "Old"


@pytest.mark.django_db
def test_delete_is_rolled_back_when_logging_fails(logged_in, monkeypatch):
    from apps.tasks import activity

    def boom(*args, **kwargs):
        raise RuntimeError("log write failed")

    monkeypatch.setattr(activity, "record_deleted", boom)
    client, user = logged_in
    task = Task.objects.create(user=user, title="Kept", status="todo")
    with pytest.raises(RuntimeError):
        client.post(reverse("boards:task-delete", args=[task.pk]))
    assert Task.objects.filter(pk=task.pk).exists()


@pytest.mark.django_db
def test_move_view_records_status(logged_in):
    client, user = logged_in
    task = Task.objects.create(user=user, title="T", status="todo")
    client.post(reverse("boards:task-move", args=[task.pk]), {"new_status": "done"})
    assert _actions(task.pk) == [("moved", "status", "web")]


@pytest.mark.django_db
def test_delete_view_records_deleted(logged_in):
    client, user = logged_in
    task = Task.objects.create(user=user, title="Doomed", status="todo")
    pk = task.pk
    client.post(reverse("boards:task-delete", args=[pk]))
    assert not Task.objects.filter(pk=pk).exists()
    assert _actions(pk) == [("deleted", "", "web")]


@pytest.mark.django_db
def test_archive_done_records_one_row_per_archived_task(logged_in):
    client, user = logged_in
    board = Board.objects.get(user=user)
    done = Task.objects.create(user=user, title="D", status="done", completed_at=timezone.now())
    active = Task.objects.create(user=user, title="A", status="todo")
    client.post(reverse("boards:board-archive-done"), {"board_id": board.pk})
    assert _actions(done.pk) == [("archived", "", "web")]
    assert _actions(active.pk) == []


@pytest.mark.django_db
def test_calendar_reschedule_records_due_date(logged_in):
    client, user = logged_in
    task = Task.objects.create(user=user, title="T", due_date=date(2026, 3, 1))
    client.post(reverse("calendar:task-reschedule", args=[task.pk]), {"due_date": "2026-03-04"})
    assert _actions(task.pk) == [("updated", "due_date", "web")]


@pytest.mark.django_db
def test_comment_create_sets_author_and_records(logged_in):
    client, user = logged_in
    task = Task.objects.create(user=user, title="T")
    client.post(reverse("boards:task-comment-create", args=[task.pk]), {"body": "hi"})
    comment = TaskComment.objects.get(task=task)
    assert comment.author == user
    assert _actions(task.pk) == [("commented", "", "web")]


@pytest.mark.django_db
def test_comment_delete_records(logged_in):
    client, user = logged_in
    task = Task.objects.create(user=user, title="T")
    comment = TaskComment.objects.create(task=task, body="x", author=user)
    client.post(reverse("boards:task-comment-delete", args=[task.pk, comment.pk]))
    assert _actions(task.pk) == [("comment_deleted", "", "web")]


@pytest.mark.django_db
def test_task_panel_shows_activity(logged_in):
    client, user = logged_in
    task = Task.objects.create(user=user, title="T", status="todo")
    client.post(reverse("boards:task-move", args=[task.pk]), {"new_status": "in_progress"})
    response = client.get(reverse("boards:task-panel", args=[task.pk]))
    html = response.content.decode()
    assert "Activity" in html
    assert "moved this from" in html
    assert "Aaron" in html


@pytest.mark.django_db
def test_task_panel_hides_activity_section_without_history(logged_in):
    client, user = logged_in
    task = Task.objects.create(user=user, title="T")
    html = client.get(reverse("boards:task-panel", args=[task.pk])).content.decode()
    assert 'id="task-activity"' not in html
