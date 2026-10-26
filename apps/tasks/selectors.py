from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.workspaces.access import workspace_for

from .models import Task, TaskStatus


class InvalidStatusError(Exception):
    pass


def visible_tasks_qs(user):
    """Tasks on the workspace the user is acting in."""
    return Task.objects.filter(workspace=workspace_for(user))


def board_tasks_qs(board):
    """Tasks on this board's workspace."""
    return Task.objects.filter(workspace_id=board.workspace_id)


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
    return TaskStatus.objects.filter(workspace=workspace_for(user))


def default_status_for(user):
    """The status new tasks should start in, or None to use the first one.

    A workspace default wins. A personal workspace still honors the older
    account-level default when the workspace itself has none.
    """
    workspace = workspace_for(user)
    if workspace.default_status_id:
        status = TaskStatus.objects.filter(
            pk=workspace.default_status_id, workspace=workspace
        ).first()
        if status:
            return status
    from apps.workspaces.models import Workspace

    if (
        workspace.kind == Workspace.KIND_PERSONAL
        and workspace.owner_id == user.pk
        and user.default_status_id
    ):
        return TaskStatus.objects.filter(
            pk=user.default_status_id, workspace=workspace
        ).first()
    return None


def default_status_slug(user):
    """Status for a new task created without one. Matches the board's create
    panel, so a task from the API lands in a column that exists instead of a
    hard-coded "todo"."""
    default = default_status_for(user)
    if default:
        return default.slug
    first = visible_statuses_qs(user).first()
    return first.slug if first else "todo"


def resolve_status_for_task(task):
    """The TaskStatus row matching task.status."""
    return TaskStatus.objects.filter(workspace_id=task.workspace_id, slug=task.status).first()


def move_task(user, task, new_status_slug, *, source="web"):
    """Move a task to a new status, recording completion state.

    Tracks the status a task was completed from in `previous_status` (cleared on
    any move back out) so reopening a task can restore the column it came from
    instead of the board's generic active status. Moving between two is_done
    statuses (e.g. Done -> Archived) leaves completed_at/previous_status alone,
    since the task never actually left the completed state.
    """
    task_statuses = TaskStatus.objects.filter(workspace_id=task.workspace_id)
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

    from apps.tasks import activity
    from apps.tasks.models import TaskActivity

    # The move, the spawned recurrence and their history rows land together or
    # not at all.
    with transaction.atomic():
        task.save(update_fields=update_fields)

        if previous_status != new_status_slug:
            activity.record(
                task, TaskActivity.MOVED, actor=user, source=source,
                field="status", old=previous_status, new=new_status_slug,
            )

        task.spawned_recurrence = None
        if is_done and not was_already_done:
            task.spawned_recurrence = task.spawn_recurrence(
                completion_date=timezone.localdate(task.completed_at)
            )
            if task.spawned_recurrence is not None:
                activity.record_created(
                    task.spawned_recurrence, actor=None, source=TaskActivity.SOURCE_SYSTEM
                )

    return task


def reschedule_task(user, task, new_due_date, *, source="web"):
    """Move a task to a new due_date, or clear it. Clears due_time too when the
    date is cleared, since a time-of-day is meaningless without a date -- otherwise
    a later re-add of a due_date would silently resurrect a stale due_time."""
    from apps.tasks import activity

    before = activity.snapshot(task)
    task.due_date = new_due_date
    if new_due_date is None:
        task.due_time = None
    with transaction.atomic():
        task.save(update_fields=["due_date", "due_time", "updated_at"])
        activity.record_changes(task, before, actor=user, source=source)
    return task
