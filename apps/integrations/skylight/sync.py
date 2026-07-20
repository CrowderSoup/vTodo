import datetime

from django.utils import timezone as dj_timezone

from apps.integrations.models import ExternalLink, SkylightMemberMapping
from apps.integrations.skylight.client import SkylightAPIError, SkylightAuthError, SkylightClient
from apps.tasks.models import Task

# How far back/forward to look for events each poll. Bounds an otherwise unbounded
# query -- a task due further out than this simply syncs once it enters the window.
WINDOW_PAST_DAYS = 7
WINDOW_FUTURE_DAYS = 180
DEFAULT_DURATION_MINUTES = 30


def _task_eligible(task) -> bool:
    return task.due_date is not None and not task.is_archived and task.completed_at is None


def _task_start_end(task):
    """Returns (start, end) aware UTC datetimes, or (None, None) for an all-day task.

    The app runs entirely in UTC (TIME_ZONE=UTC, USE_TZ=True; there's no per-user/team
    timezone yet), so due_time is treated as a UTC wall-clock time. The instant is
    still correct wherever the frame itself is configured.
    """
    if task.due_time is None:
        return None, None
    naive = datetime.datetime.combine(task.due_date, task.due_time)
    start = dj_timezone.make_aware(naive, datetime.timezone.utc)
    duration = task.duration_minutes or DEFAULT_DURATION_MINUTES
    return start, start + datetime.timedelta(minutes=duration)


def _category_ids_for_assignee(connection, assignee_id):
    if assignee_id is None:
        return []
    mapping = SkylightMemberMapping.objects.filter(connection=connection, user_id=assignee_id).first()
    return [mapping.category_id] if mapping else []


def _local_snapshot_from_task(task, connection):
    """Normalized, comparable view of a task's sync-relevant fields -- used to
    detect local drift against the last-synced snapshot. Always built from the
    task's own fields so two snapshots taken this way are directly comparable,
    regardless of how any other field on the task (status, order, tags, ...)
    changed in between."""
    start, end = _task_start_end(task)
    all_day = start is None
    return {
        "summary": task.title,
        "description": task.notes,
        "all_day": all_day,
        "starts_at": start.isoformat() if start else task.due_date.isoformat(),
        "ends_at": end.isoformat() if end else task.due_date.isoformat(),
        "category_ids": sorted(_category_ids_for_assignee(connection, task.assignee_id)),
    }


def _payload_for_task(task, connection):
    # connection.calendar_id is just a display label (email/name/...), not a
    # Skylight-editable resource field -- sending it makes Skylight reject the
    # request with "calendar_id: is not editable". Only calendar_account_id
    # identifies which calendar the event belongs to.
    snapshot = _local_snapshot_from_task(task, connection)
    return {
        **snapshot,
        "calendar_account_id": connection.calendar_account_id,
        "kind": "standard",
        "timezone": "UTC",
    }


def _snapshot_from_event(event):
    """Normalized, comparable view of a Skylight event resource -- used to detect
    drift against the last-synced snapshot. Always built from Skylight's own
    response so two snapshots taken this way are directly comparable."""
    attrs = event["attributes"]
    category_ids = sorted(
        c["id"] for c in event.get("relationships", {}).get("categories", {}).get("data", [])
    )
    return {
        "summary": attrs.get("summary") or "",
        "description": attrs.get("description") or "",
        "all_day": bool(attrs.get("all_day")),
        "starts_at": attrs.get("starts_at"),
        "ends_at": attrs.get("ends_at"),
        "category_ids": category_ids,
    }


def _assignee_id_from_category_ids(connection, category_ids):
    from apps.teams.models import TeamMembership

    for category_id in category_ids:
        mapping = SkylightMemberMapping.objects.filter(
            connection=connection, category_id=category_id
        ).first()
        if mapping and mapping.user_id:
            still_a_member = TeamMembership.objects.filter(
                team_id=connection.team_id, user_id=mapping.user_id
            ).exists()
            if still_a_member:
                return mapping.user_id
    return None


def _apply_event_to_task(task, event, connection):
    attrs = event["attributes"]
    starts_at = attrs.get("starts_at")

    task.title = attrs.get("summary") or task.title
    task.notes = attrs.get("description") or ""
    if starts_at:
        dt = datetime.datetime.fromisoformat(starts_at)
        if dt.tzinfo is not None:
            dt = dt.astimezone(datetime.timezone.utc)
        task.due_date = dt.date()
        task.due_time = None if attrs.get("all_day") else dt.time()

    category_ids = [c["id"] for c in event.get("relationships", {}).get("categories", {}).get("data", [])]
    task.assignee_id = _assignee_id_from_category_ids(connection, category_ids)

    task.save(update_fields=["title", "notes", "due_date", "due_time", "assignee", "updated_at"])


def _reconcile_linked_tasks(connection, client, remote_events):
    """Push/pull/retire each task already linked to a Skylight event. Returns the
    set of task ids that are linked (whether the link survived this pass or not),
    so the caller knows which local tasks still need a first-time push."""
    links = ExternalLink.objects.filter(
        provider=ExternalLink.Provider.SKYLIGHT,
        task__team_id=connection.team_id,
    ).select_related("task")

    seen_task_ids = set()

    for link in links:
        task = link.task
        seen_task_ids.add(task.id)
        remote_event = remote_events.get(link.external_id)

        if remote_event is None:
            # Deleted on the Skylight side (or fell out of the poll window) -- drop
            # the link. If the task is still eligible it gets recreated next pass.
            link.delete()
            continue

        if not _task_eligible(task):
            client.delete_calendar_event(link.external_id)
            link.delete()
            continue

        remote_snapshot = _snapshot_from_event(remote_event)
        local_snapshot = _local_snapshot_from_task(task, connection)
        synced = link.metadata or {}
        remote_changed = remote_snapshot != synced.get("remote")
        # Compared against the local snapshot stored at last sync, not task.updated_at:
        # updated_at is bumped by any save (status move, reorder, tag edit, ...), so a
        # timestamp check would treat unrelated edits as "local changed" and clobber a
        # genuine concurrent remote edit even though no synced field actually moved.
        local_changed = link.synced_at is None or local_snapshot != synced.get("local")

        if local_changed:
            # Covers "only local changed" and "both changed since last sync." Skylight
            # exposes no modified-at timestamp on events, so true dual-clock
            # last-write-wins isn't possible -- local wins ties, since the local
            # snapshot is the only reliable signal available.
            event = client.update_calendar_event(link.external_id, _payload_for_task(task, connection))
            link.metadata = {"remote": _snapshot_from_event(event), "local": local_snapshot}
            link.synced_at = dj_timezone.now()
            link.save(update_fields=["metadata", "synced_at"])
        elif remote_changed:
            _apply_event_to_task(task, remote_event, connection)
            link.metadata = {
                "remote": remote_snapshot,
                "local": _local_snapshot_from_task(task, connection),
            }
            link.synced_at = dj_timezone.now()
            link.save(update_fields=["metadata", "synced_at"])

    return seen_task_ids


def _push_new_tasks(connection, client, already_linked_task_ids):
    new_tasks = Task.objects.filter(
        team_id=connection.team_id,
        due_date__isnull=False,
        is_archived=False,
        completed_at__isnull=True,
    ).exclude(id__in=already_linked_task_ids)

    for task in new_tasks:
        event = client.create_calendar_event(_payload_for_task(task, connection))
        ExternalLink.objects.create(
            task=task,
            provider=ExternalLink.Provider.SKYLIGHT,
            external_id=event["id"],
            synced_at=dj_timezone.now(),
            metadata={
                "remote": _snapshot_from_event(event),
                "local": _local_snapshot_from_task(task, connection),
            },
        )


def sync_connection(connection):
    """Reconcile one team's Skylight connection. Raises on failure so the caller
    (the Celery task) can isolate failures per-connection; also records the error
    on the connection itself so it's visible in the settings UI."""
    if not connection.is_active or not connection.is_ready:
        return

    client = SkylightClient(connection)
    now = dj_timezone.now()
    date_min = (now - datetime.timedelta(days=WINDOW_PAST_DAYS)).date().isoformat()
    date_max = (now + datetime.timedelta(days=WINDOW_FUTURE_DAYS)).date().isoformat()

    try:
        remote_events = {event["id"]: event for event in client.list_calendar_events(date_min, date_max)}
        linked_task_ids = _reconcile_linked_tasks(connection, client, remote_events)
        _push_new_tasks(connection, client, linked_task_ids)
    except (SkylightAPIError, SkylightAuthError) as exc:
        connection.last_sync_error = str(exc)
        connection.save(update_fields=["last_sync_error"])
        raise

    connection.last_synced_at = dj_timezone.now()
    connection.last_sync_error = ""
    connection.save(update_fields=["last_synced_at", "last_sync_error"])
