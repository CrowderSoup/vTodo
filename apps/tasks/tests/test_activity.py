from datetime import date

import pytest

from apps.tasks import activity
from apps.tasks.models import Task, TaskActivity, TaskComment
from apps.tasks.selectors import move_task, reschedule_task
from apps.users.models import User


def _rows(task):
    return list(TaskActivity.objects.filter(task_pk=task.pk).order_by("pk"))


@pytest.mark.django_db
def test_record_changes_writes_one_row_per_changed_field():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Old", tags=["a"])
    before = activity.snapshot(task)
    task.title = "New"
    task.tags = ["a", "b"]
    task.due_date = date(2026, 11, 1)
    task.save()

    rows = activity.record_changes(task, before, actor=user, source=TaskActivity.SOURCE_WEB)

    got = {(r.field, r.old_value, r.new_value) for r in rows}
    assert got == {("title", "Old", "New"), ("tags", "a", "a, b"), ("due_date", "", "2026-11-01")}
    assert all(r.user_id == user.pk and r.actor == user and r.action == "updated" for r in rows)


@pytest.mark.django_db
def test_record_changes_is_silent_when_nothing_changed():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Same")
    before = activity.snapshot(task)
    task.save()
    assert activity.record_changes(task, before, actor=user, source="web") == []
    assert TaskActivity.objects.count() == 0


@pytest.mark.django_db
def test_notes_changes_never_store_the_text():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="T", notes="secret old")
    before = activity.snapshot(task)
    task.notes = "secret new"
    activity.record_changes(task, before, actor=user, source="web")
    (row,) = _rows(task)
    assert row.field == "notes"
    assert row.old_value == "" and row.new_value == ""


@pytest.mark.django_db
def test_notes_line_ending_change_alone_records_nothing():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="T", notes="one\ntwo")
    before = activity.snapshot(task)
    task.notes = "one\r\ntwo"
    assert activity.record_changes(task, before, actor=user, source="web") == []


@pytest.mark.django_db
def test_long_values_are_truncated_to_column_size():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="x")
    before = activity.snapshot(task)
    task.title = "y" * 500
    activity.record_changes(task, before, actor=user, source="web")
    (row,) = _rows(task)
    assert len(row.new_value) == 255
    assert row.new_value.endswith("…")


@pytest.mark.django_db
def test_archive_flag_records_archived_and_unarchived():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="T")
    before = activity.snapshot(task)
    task.is_archived = True
    activity.record_changes(task, before, actor=user, source="api")
    before = activity.snapshot(task)
    task.is_archived = False
    activity.record_changes(task, before, actor=user, source="api")
    assert [r.action for r in _rows(task)] == ["archived", "unarchived"]


@pytest.mark.django_db
def test_activity_is_append_only():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="T")
    row = activity.record(task, TaskActivity.CREATED, actor=user, source="web")
    row.new_value = "tampered"
    with pytest.raises(ValueError):
        row.save()
    with pytest.raises(ValueError):
        row.delete()


@pytest.mark.django_db
def test_activity_queryset_blocks_bulk_update_and_delete():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="T")
    activity.record_created(task, actor=user, source="web")
    rows = TaskActivity.objects.filter(task_pk=task.pk)
    with pytest.raises(ValueError):
        rows.update(new_value="tampered")
    with pytest.raises(ValueError):
        rows.delete()
    assert rows.get().new_value == "T"


@pytest.mark.django_db
def test_history_survives_task_deletion():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Gone soon")
    pk = task.pk
    activity.record_created(task, actor=user, source="web")
    activity.record_deleted(task, actor=user, source="web")
    task.delete()

    rows = list(TaskActivity.objects.filter(user=user, task_pk=pk).order_by("pk"))
    assert [r.action for r in rows] == ["created", "deleted"]
    assert rows[1].old_value == "Gone soon"
    assert all(r.task_id is None for r in rows)


@pytest.mark.django_db
def test_deleting_actor_keeps_rows_but_deleting_owner_removes_them():
    owner = User.objects.create_user()
    other = User.objects.create_user()
    task = Task.objects.create(user=owner, title="T")
    activity.record_created(task, actor=other, source="api")
    other.delete()
    row = TaskActivity.objects.get(task_pk=task.pk)
    assert row.actor is None
    owner.delete()
    assert TaskActivity.objects.count() == 0


@pytest.mark.django_db
def test_move_task_records_status_change_with_source():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="T", status="todo")
    move_task(user, task, "in_progress", source="mcp")
    (row,) = _rows(task)
    assert (row.action, row.field, row.old_value, row.new_value, row.source) == (
        "moved", "status", "todo", "in_progress", "mcp",
    )


@pytest.mark.django_db
def test_move_task_is_rolled_back_when_logging_fails(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("log write failed")

    monkeypatch.setattr(activity, "record", boom)
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="T", status="todo")
    with pytest.raises(RuntimeError):
        move_task(user, task, "done")
    task.refresh_from_db()
    assert (task.status, task.completed_at) == ("todo", None)


@pytest.mark.django_db
def test_move_task_to_same_status_records_nothing():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="T", status="todo")
    move_task(user, task, "todo")
    assert _rows(task) == []


@pytest.mark.django_db
def test_completing_recurring_task_logs_system_created_spawn():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Weekly", status="todo", recurrence_days=7)
    move_task(user, task, "done")
    spawned = task.spawned_recurrence
    assert spawned is not None
    (row,) = _rows(spawned)
    assert row.action == "created"
    assert row.source == "system"
    assert row.actor is None


@pytest.mark.django_db
def test_reschedule_records_due_date_change():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="T", due_date=date(2026, 1, 1))
    reschedule_task(user, task, date(2026, 1, 5))
    (row,) = _rows(task)
    assert (row.field, row.old_value, row.new_value) == ("due_date", "2026-01-01", "2026-01-05")


@pytest.mark.django_db
def test_comment_activity_stores_comment_id_not_body():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="T")
    comment = TaskComment.objects.create(task=task, body="private words", author=user)
    activity.record_comment(comment, TaskActivity.COMMENTED, actor=user, source="web")
    (row,) = _rows(task)
    assert row.new_value == str(comment.pk)
    assert "private" not in row.old_value + row.new_value
