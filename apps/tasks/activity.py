"""Recording task history (TaskActivity).

Callers snapshot a task before changing it and hand the snapshot back
afterwards; only fields that actually changed get a row. Status changes are
recorded by move_task itself so every path (board, panel, API, MCP) logs them
exactly once.
"""

from apps.tasks.models import TaskActivity

# Fields whose changes are worth a history row. Notes are tracked, but only as
# "changed" -- their text is never copied into the log.
TRACKED_FIELDS = (
    "title",
    "notes",
    "due_date",
    "due_time",
    "duration_minutes",
    "tags",
    "recurrence_days",
    "recurrence_from",
)
_VALUELESS_FIELDS = {"notes"}
_MAX = 255


def _fmt(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value)
    value = str(value)
    return value if len(value) <= _MAX else value[: _MAX - 1] + "…"


def source_for_request(request):
    """web for browser sessions; mcp for OAuth tokens (only mcp_server forwards
    those -- see apps/api/permissions.py) or a client that says it is the MCP
    server; api otherwise. The header is self-reported, which is fine for a
    label on the caller's own tasks."""
    from oauth2_provider.models import get_access_token_model

    auth = getattr(request, "auth", None)
    if auth is None:
        return TaskActivity.SOURCE_WEB
    if isinstance(auth, get_access_token_model()):
        return TaskActivity.SOURCE_MCP
    if request.headers.get("X-Vtodo-Client", "").lower() == "mcp":
        return TaskActivity.SOURCE_MCP
    return TaskActivity.SOURCE_API


def _row(task, action, actor, source, field="", old="", new=""):
    return TaskActivity(
        user_id=task.user_id,
        task=task,
        task_pk=task.pk,
        actor=actor,
        source=source,
        action=action,
        field=field,
        old_value=_fmt(old),
        new_value=_fmt(new),
    )


def record(task, action, *, actor, source, field="", old="", new=""):
    row = _row(task, action, actor, source, field, old, new)
    row.save()
    return row


def snapshot(task):
    return {f: getattr(task, f) for f in TRACKED_FIELDS + ("is_archived",)}


def record_changes(task, before, *, actor, source):
    """Write one row per tracked field that differs from `before`."""
    rows = []
    for f in TRACKED_FIELDS:
        old, new = before.get(f), getattr(task, f)
        if f == "tags":
            old, new = list(old or []), list(new or [])
        if old == new:
            continue
        if f in _VALUELESS_FIELDS:
            rows.append(_row(task, TaskActivity.UPDATED, actor, source, f))
        else:
            rows.append(_row(task, TaskActivity.UPDATED, actor, source, f, old, new))
    if before.get("is_archived") != task.is_archived:
        action = TaskActivity.ARCHIVED if task.is_archived else TaskActivity.UNARCHIVED
        rows.append(_row(task, action, actor, source))
    if rows:
        TaskActivity.objects.bulk_create(rows)
    return rows


def record_created(task, *, actor, source):
    record(task, TaskActivity.CREATED, actor=actor, source=source, new=task.title)


def record_deleted(task, *, actor, source):
    """Call before task.delete(); the FK is nulled on delete, task_pk stays."""
    record(task, TaskActivity.DELETED, actor=actor, source=source, old=task.title)


def record_bulk_archived(tasks, *, actor, source):
    TaskActivity.objects.bulk_create(
        [_row(t, TaskActivity.ARCHIVED, actor, source) for t in tasks]
    )


def record_comment(comment, action, *, actor, source):
    record(comment.task, action, actor=actor, source=source, new=str(comment.pk))
