from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import Task, TaskStatus


class InvalidStatusError(Exception):
    pass


def visible_tasks_qs(user):
    """Tasks the user may see: their own tasks."""
    return Task.objects.filter(user=user)


def board_tasks_qs(board):
    """Tasks belonging on a given board: its owner's tasks."""
    return Task.objects.filter(user_id=board.user_id)


def get_task_or_404(user, pk):
    return get_object_or_404(visible_tasks_qs(user), pk=pk)


def known_tags_for_board(board):
    """Distinct tag vocabulary already used on a board's tasks, sorted -- the
    autocomplete source for the tag chip input on the create/edit task panels."""
    tags = set()
    for task_tags in board_tasks_qs(board).values_list("tags", flat=True):
        tags.update(task_tags or [])
    return sorted(tags)


def visible_statuses_qs(user):
    return TaskStatus.objects.filter(user=user)


def resolve_status_for_task(task):
    """The TaskStatus row matching task.status."""
    return TaskStatus.objects.filter(user_id=task.user_id, slug=task.status).first()


def move_task(user, task, new_status_slug):
    """Move a task to a new status, recording completion state.

    Tracks the status a task was completed from in `previous_status` (cleared on
    any move back out) so reopening a task can restore the column it came from
    instead of the board's generic active status. Moving between two is_done
    statuses (e.g. Done -> Archived) leaves completed_at/previous_status alone,
    since the task never actually left the completed state.
    """
    task_statuses = visible_statuses_qs(user)
    valid_slugs = set(task_statuses.values_list("slug", flat=True))
    if new_status_slug not in valid_slugs:
        raise InvalidStatusError(f"{new_status_slug!r} is not a valid status for this task.")

    previous_status = task.status
    task.status = new_status_slug
    is_done = task_statuses.filter(slug=new_status_slug, is_done=True).exists()
    was_already_done = task.completed_at is not None
    update_fields = ["status", "completed_at", "previous_status", "updated_at"]

    if is_done:
        if not was_already_done:
            task.completed_at = timezone.now()
            task.previous_status = previous_status
    else:
        task.completed_at = None
        task.previous_status = ""

    task.save(update_fields=update_fields)

    if is_done and not was_already_done:
        task.spawn_recurrence(completion_date=timezone.localdate(task.completed_at))

    return task


def reschedule_task(user, task, new_due_date):
    """Move a task to a new due_date, or clear it. Clears due_time too when the
    date is cleared, since a time-of-day is meaningless without a date -- otherwise
    a later re-add of a due_date would silently resurrect a stale due_time."""
    task.due_date = new_due_date
    if new_due_date is None:
        task.due_time = None
    task.save(update_fields=["due_date", "due_time", "updated_at"])
    return task
