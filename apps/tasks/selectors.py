from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import Task, TaskActivity, TaskStatus


class AssignmentError(Exception):
    pass


class InvalidStatusError(Exception):
    pass


def user_team_ids(user):
    return list(user.team_memberships.values_list("team_id", flat=True))


def user_teams_qs(user):
    from apps.teams.models import Team

    return Team.objects.filter(memberships__user=user)


def visible_tasks_qs(user):
    """Tasks the user may see: their own personal tasks + any task on a team they belong to."""
    return Task.objects.filter(
        Q(user=user, team__isnull=True) | Q(team_id__in=user_team_ids(user))
    )


def board_tasks_qs(board):
    """Tasks belonging on a given board: a team board shows all of that team's tasks,
    a personal board shows only its owner's personal (non-team) tasks."""
    if board.team_id:
        return Task.objects.filter(team_id=board.team_id)
    return Task.objects.filter(user_id=board.user_id, team__isnull=True)


def get_task_or_404(user, pk):
    return get_object_or_404(visible_tasks_qs(user), pk=pk)


def visible_statuses_qs(user, team=None):
    if team is not None:
        return TaskStatus.objects.filter(team=team)
    return TaskStatus.objects.filter(user=user, team__isnull=True)


def all_visible_statuses_qs(user):
    """Every status the user can use: their personal statuses plus every team's they belong to."""
    return TaskStatus.objects.filter(
        Q(user=user, team__isnull=True) | Q(team_id__in=user_team_ids(user))
    ).select_related("team")


def resolve_status_for_task(task):
    """The TaskStatus row matching task.status, scoped to whoever/whatever owns the task."""
    if task.team_id:
        qs = TaskStatus.objects.filter(team_id=task.team_id)
    else:
        qs = TaskStatus.objects.filter(user_id=task.user_id, team__isnull=True)
    return qs.filter(slug=task.status).first()


def move_task(user, task, new_status_slug):
    """Move a task to a new status, recording completion state.

    Tracks the status a task was completed from in `previous_status` (cleared on
    any move back out) so reopening a task can restore the column it came from
    instead of the board's generic active status. Moving between two is_done
    statuses (e.g. Done -> Archived) leaves completed_at/previous_status alone,
    since the task never actually left the completed state.
    """
    task_statuses = visible_statuses_qs(user, team=task.team)
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
        task.spawn_recurrence(completion_date=task.completed_at.date())

    return task


def assign_task(actor, task, new_assignee):
    from apps.teams.models import TeamMembership

    if task.team_id is None:
        raise AssignmentError("Only team tasks can be assigned.")
    if new_assignee is not None and not TeamMembership.objects.filter(
        team_id=task.team_id, user=new_assignee
    ).exists():
        raise AssignmentError("Assignee must be a member of the task's team.")

    def _display(u):
        if u is None:
            return "Unassigned"
        return u.display_name or u.username

    old_display = _display(task.assignee)
    new_display = _display(new_assignee)

    task.assignee = new_assignee
    task.save(update_fields=["assignee", "updated_at"])
    TaskActivity.objects.create(
        task=task, actor=actor, field="assignee", old_value=old_display, new_value=new_display
    )
    return task
