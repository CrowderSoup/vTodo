import datetime

from django.db.models import Q
from django.utils import timezone as dj_timezone

from apps.integrations.google_calendar.client import GoogleCalendarAPIError, GoogleCalendarAuthError, GoogleCalendarClient
from apps.integrations.models import ExternalLink
from apps.tasks.models import Task

DEFAULT_DURATION_MINUTES = 30


def owned_or_assigned_tasks_qs(user):
    """A user's own personal tasks plus any team task assigned to them --
    everything relevant to that person's calendar. Mirrors the personal/team
    split already enforced in apps.tasks.selectors.visible_tasks_qs. Public
    since the disconnect view also needs it, to clean up ExternalLinks."""
    return Task.objects.filter(Q(user=user, team__isnull=True) | Q(assignee=user))


def _eligible_tasks_qs(user):
    return owned_or_assigned_tasks_qs(user).filter(
        due_date__isnull=False, is_archived=False, completed_at__isnull=True,
    )


def _task_start_end(task):
    """Returns (start, end) aware UTC datetimes, or (None, None) for an all-day task.
    The app runs entirely in UTC (TIME_ZONE=UTC, USE_TZ=True), so due_time is
    treated as a UTC wall-clock time."""
    if task.due_time is None:
        return None, None
    naive = datetime.datetime.combine(task.due_date, task.due_time)
    start = dj_timezone.make_aware(naive, datetime.UTC)
    duration = task.duration_minutes or DEFAULT_DURATION_MINUTES
    return start, start + datetime.timedelta(minutes=duration)


def _payload_for_task(task):
    start, end = _task_start_end(task)
    if start is None:
        return {
            "summary": task.title,
            "description": task.notes,
            "start": {"date": task.due_date.isoformat()},
            "end": {"date": task.due_date.isoformat()},
        }
    return {
        "summary": task.title,
        "description": task.notes,
        "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
    }


def _local_snapshot(task):
    """Only the fields that actually feed the event payload. Diffing against this
    -- instead of task.updated_at -- means an edit to something sync-irrelevant
    (tags, board position, ...) never triggers a spurious push."""
    return {
        "title": task.title,
        "notes": task.notes,
        "due_date": task.due_date.isoformat(),
        "due_time": task.due_time.isoformat() if task.due_time else None,
        "duration_minutes": task.duration_minutes,
    }


def _reconcile_linked_tasks(connection, client, eligible_by_id):
    """Push/update/retire each task already linked to an event in this user's
    vTodo calendar. Returns the set of task ids that are linked (whether the
    link survived this pass or not), so the caller knows which eligible tasks
    still need a first-time push."""
    links = ExternalLink.objects.filter(
        provider=ExternalLink.Provider.GOOGLE_CALENDAR,
        task__in=owned_or_assigned_tasks_qs(connection.user),
    ).select_related("task")

    seen_task_ids = set()

    for link in links:
        task = link.task
        seen_task_ids.add(task.id)

        if task.id not in eligible_by_id:
            # No longer eligible (archived, completed, due date cleared) or the
            # task itself is gone -- retire the event and drop the link.
            client.delete_event(connection.calendar_id, link.external_id)
            link.delete()
            continue

        snapshot = _local_snapshot(task)
        if snapshot != link.metadata:
            client.update_event(connection.calendar_id, link.external_id, _payload_for_task(task))
            link.metadata = snapshot
            link.synced_at = dj_timezone.now()
            link.save(update_fields=["metadata", "synced_at"])

    return seen_task_ids


def _push_new_tasks(connection, client, eligible_by_id, already_linked_task_ids):
    for task_id, task in eligible_by_id.items():
        if task_id in already_linked_task_ids:
            continue
        event = client.create_event(connection.calendar_id, _payload_for_task(task))
        ExternalLink.objects.create(
            task=task,
            provider=ExternalLink.Provider.GOOGLE_CALENDAR,
            external_id=event["id"],
            synced_at=dj_timezone.now(),
            metadata=_local_snapshot(task),
        )


def sync_connection(connection):
    """Reconcile one user's vTodo calendar. Raises on failure so the caller (the
    Celery task) can isolate failures per-connection; also records the error on
    the connection itself so it's visible in the settings UI."""
    if not connection.is_active:
        return

    client = GoogleCalendarClient(connection)
    eligible_by_id = {task.id: task for task in _eligible_tasks_qs(connection.user)}

    try:
        linked_task_ids = _reconcile_linked_tasks(connection, client, eligible_by_id)
        _push_new_tasks(connection, client, eligible_by_id, linked_task_ids)
    except GoogleCalendarAuthError as exc:
        connection.is_active = False
        connection.last_sync_error = str(exc)
        connection.save(update_fields=["is_active", "last_sync_error"])
        raise
    except GoogleCalendarAPIError as exc:
        connection.last_sync_error = str(exc)
        connection.save(update_fields=["last_sync_error"])
        raise

    connection.last_synced_at = dj_timezone.now()
    connection.last_sync_error = ""
    connection.save(update_fields=["last_synced_at", "last_sync_error"])
