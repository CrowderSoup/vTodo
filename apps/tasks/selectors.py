from django.db.models import Q
from django.shortcuts import get_object_or_404

from .models import Task, TaskActivity, TaskStatus


class AssignmentError(Exception):
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
