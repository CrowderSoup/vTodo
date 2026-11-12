"""Export tasks as an iCalendar (RFC 5545) file of VTODOs.

One VTODO per task. The standard has no home for comments, activity, custom
statuses, assignees, claims or workspaces, so those are left out. A few vTodo
fields go out as X-VTODO-* properties so a vTodo import gets them back; other
apps ignore unknown X- properties.

- Due dates without a time are DATE values. A due time is UTC (the app runs in
  UTC, see apps/integrations/google_calendar/sync.py), so it is written as a
  UTC DATE-TIME.
- A recurring task gets RRULE:FREQ=DAILY;INTERVAL=n and a DTSTART, which RFC
  5545 requires alongside an RRULE. DTSTART is the due date, or the day the
  task was created when it has none. Repeating from completion can't be said
  in an RRULE, so it also gets X-VTODO-RECUR-FROM:COMPLETION; other apps will
  treat it as repeating from the due date.
- A completed task is the finished copy of its series (completing one spawns
  the next), so it is written without an RRULE. Otherwise other apps would see
  two copies of the same series.
"""

import datetime

from django.utils import timezone
from django.utils.text import slugify

PRODID = "-//CrowderSoup//vTodo//EN"
CONTENT_TYPE = "text/calendar; charset=utf-8"

RECUR_FROM_PROPERTY = "X-VTODO-RECUR-FROM"
DURATION_PROPERTY = "X-VTODO-DURATION"
ARCHIVED_PROPERTY = "X-VTODO-ARCHIVED"

_MAX_LINE_OCTETS = 75


def escape_text(value):
    """Escape a TEXT value (RFC 5545 3.3.11)."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
    )


def fold(line):
    """Fold a content line to at most 75 octets per line (RFC 5545 3.1),
    without splitting a UTF-8 character."""
    out = []
    current = ""
    size = 0
    limit = _MAX_LINE_OCTETS
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > limit:
            out.append(current)
            # Continuation lines start with a space, which counts as an octet.
            current, size, limit = "", 0, _MAX_LINE_OCTETS - 1
        current += char
        size += width
    out.append(current)
    return "\r\n ".join(out)


def _utc(dt):
    return timezone.localtime(dt, datetime.UTC).strftime("%Y%m%dT%H%M%SZ")


def _date(d):
    return d.strftime("%Y%m%d")


def _due_property(name, task):
    """DTSTART/DUE for the task's due date, with its time when it has one."""
    if task.due_time is None:
        return f"{name};VALUE=DATE:{_date(task.due_date)}"
    due = datetime.datetime.combine(task.due_date, task.due_time, tzinfo=datetime.UTC)
    return f"{name}:{_utc(due)}"


def _duration(minutes):
    hours, mins = divmod(minutes, 60)
    return "PT" + (f"{hours}H" if hours else "") + (f"{mins}M" if mins or not hours else "")


def vtodo_lines(task):
    """The content lines (unfolded) of one task's VTODO."""
    lines = [
        "BEGIN:VTODO",
        f"UID:{escape_text(task.ical_uid)}",
        # With no METHOD, DTSTAMP is when the task was last revised (3.8.7.2).
        f"DTSTAMP:{_utc(task.updated_at)}",
        f"SUMMARY:{escape_text(task.title)}",
    ]
    if task.notes:
        lines.append(f"DESCRIPTION:{escape_text(task.notes)}")
    tags = [t for t in (task.tags or []) if t]
    if tags:
        lines.append("CATEGORIES:" + ",".join(escape_text(t) for t in tags))

    recurs = bool(task.recurrence_days) and task.completed_at is None
    if recurs:
        if task.due_date:
            lines.append(_due_property("DTSTART", task))
        else:
            created = timezone.localtime(task.created_at, datetime.UTC).date()
            lines.append(f"DTSTART;VALUE=DATE:{_date(created)}")
    if task.due_date:
        lines.append(_due_property("DUE", task))
    if recurs:
        lines.append(f"RRULE:FREQ=DAILY;INTERVAL={task.recurrence_days}")
        if task.recurrence_from == task.RECURRENCE_FROM_COMPLETION:
            lines.append(f"{RECUR_FROM_PROPERTY}:COMPLETION")

    if task.completed_at:
        lines.append("STATUS:COMPLETED")
        lines.append(f"COMPLETED:{_utc(task.completed_at)}")
    else:
        lines.append("STATUS:NEEDS-ACTION")

    if task.duration_minutes:
        lines.append(f"{DURATION_PROPERTY}:{_duration(task.duration_minutes)}")
    if task.is_archived:
        lines.append(f"{ARCHIVED_PROPERTY}:TRUE")
    lines.append("END:VTODO")
    return lines


def export_tasks(tasks):
    """An iCalendar document (str, CRLF line endings) holding `tasks`."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN"]
    for task in tasks:
        lines.extend(vtodo_lines(task))
    lines.append("END:VCALENDAR")
    return "".join(fold(line) + "\r\n" for line in lines)


def workspace_tasks(workspace):
    """Every task in the workspace, archived and done ones included, oldest
    first so the file is stable from one export to the next."""
    from .models import Task

    return Task.objects.filter(workspace=workspace).order_by("created_at", "pk")


def export_filename(workspace, today=None):
    today = today or timezone.now().date()
    return f"vtodo-{slugify(workspace.name) or 'tasks'}-{today.isoformat()}.ics"


def export_response(workspace):
    """An attachment response with the workspace's tasks as .ics."""
    from django.http import HttpResponse

    response = HttpResponse(export_tasks(workspace_tasks(workspace)), content_type=CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{export_filename(workspace)}"'
    return response
