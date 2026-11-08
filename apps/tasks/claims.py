"""Assigning tasks, and lease-based claims on them.

A claim says "I'm working on this until claim_expires_at". It is how an agent
polling for assigned work avoids two workers picking up the same task. The
holder renews it by claiming again before it lapses. Once it lapses anyone
can claim the task. Claims are advisory: they do not lock the task.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.tasks import activity
from apps.tasks.models import Task, TaskActivity, TaskStatus

DEFAULT_LEASE = timedelta(minutes=15)
MIN_LEASE = timedelta(seconds=30)
MAX_LEASE = timedelta(hours=24)
# claim-next tries this many candidates before giving up for this call.
CLAIM_NEXT_ATTEMPTS = 20


class ClaimConflict(Exception):
    """Someone else holds an unexpired claim on the task."""

    def __init__(self, task):
        self.task = task
        holder = task.claimed_by
        name = (holder.display_name or holder.username) if holder else "someone else"
        if task.claim_expires_at is None:
            super().__init__(f"Claimed by {name}. Try again.")
        else:
            super().__init__(f"Claimed by {name} until {task.claim_expires_at.isoformat()}.")


def lease_from(seconds):
    """A lease length from a number of seconds, kept within bounds. None means
    the default. Raises ValueError for anything that isn't a whole number."""
    if seconds is None or seconds == "":
        return DEFAULT_LEASE
    if isinstance(seconds, bool):
        raise ValueError("lease_seconds must be a whole number of seconds.")
    try:
        lease = timedelta(seconds=int(seconds))
    except (TypeError, ValueError):
        raise ValueError("lease_seconds must be a whole number of seconds.")
    return min(max(lease, MIN_LEASE), MAX_LEASE)


def assignable_users(workspace):
    """People who can change tasks in `workspace`, and their agents."""
    from apps.users.models import User
    from apps.workspaces.models import Membership

    writers = Membership.objects.filter(
        workspace=workspace, role__in=(Membership.ROLE_OWNER, Membership.ROLE_MEMBER)
    ).values("user_id")
    return User.objects.filter(
        Q(pk__in=writers) | Q(kind=User.KIND_AGENT, parent_id__in=writers),
        is_active=True,
    ).order_by("kind", "display_name", "pk")


def _claimable(now):
    return Q(claimed_by__isnull=True) | Q(claim_expires_at__isnull=True) | Q(claim_expires_at__lte=now)


def claim_task(task, user, *, lease=DEFAULT_LEASE, source="api"):
    """Claim `task` for `user`, or renew their claim. Raises ClaimConflict
    while someone else's claim is live."""
    now = timezone.now()
    renewing = task.active_claim_holder_id(now) == user.pk
    with transaction.atomic():
        updated = (
            Task.objects.filter(pk=task.pk)
            .filter(_claimable(now) | Q(claimed_by=user))
            .update(claimed_by=user, claim_expires_at=now + lease)
        )
        task.refresh_from_db(fields=["claimed_by", "claim_expires_at"])
        if not updated:
            raise ClaimConflict(task)
        if not renewing:
            activity.record(task, TaskActivity.CLAIMED, actor=user, source=source)
    return task


def release_task(task, user, *, source="api"):
    """Drop the claim on `task`. A person may release anyone's claim. An agent
    may only release its own."""
    now = timezone.now()
    holder_id = task.active_claim_holder_id(now)
    if holder_id is not None and holder_id != user.pk and user.is_agent:
        raise ClaimConflict(task)
    with transaction.atomic():
        Task.objects.filter(pk=task.pk).update(claimed_by=None, claim_expires_at=None)
        task.claimed_by = None
        task.claim_expires_at = None
        if holder_id is not None:
            activity.record(task, TaskActivity.RELEASED, actor=user, source=source)
    return task


def open_assigned_tasks(user, workspace):
    """Tasks assigned to `user` that are still to do, in board order."""
    done_slugs = TaskStatus.objects.filter(workspace=workspace, is_done=True).values("slug")
    return (
        Task.objects.filter(
            workspace=workspace, assignee=user, is_archived=False, completed_at__isnull=True
        )
        .exclude(status__in=done_slugs)
        .order_by("order", "created_at", "pk")
    )


def claim_next_task(user, workspace, *, lease=DEFAULT_LEASE, source="api"):
    """Claim the first open task assigned to `user` that nobody holds, or
    return None. Tasks `user` already holds are skipped, so a dispatcher that
    polls this gets each task once."""
    now = timezone.now()
    candidates = open_assigned_tasks(user, workspace).filter(_claimable(now))
    for task in candidates[:CLAIM_NEXT_ATTEMPTS]:
        try:
            return claim_task(task, user, lease=lease, source=source)
        except ClaimConflict:
            # Another worker got there first.
            continue
    return None
