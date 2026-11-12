"""Import tasks from an iCalendar (RFC 5545) file of VTODOs.

The partner of apps/tasks/ical.py: a vTodo export imported into an empty
workspace exports again to the same file (DTSTAMP aside, which is the time
the file was written). Files from other apps work too. Everything other than
VTODOs (events, journals, alarms, time zone definitions) is ignored.

- Tasks are matched on UID within the workspace, so importing the same file
  twice changes nothing the second time. A matched task is updated to what the
  file says. A VTODO without a UID is always added as a new task.
- import_ics(dry_run=True) works out what would happen and writes nothing.
- DUE becomes the due date, and its time when it has one. Times are stored in
  UTC (see ical.py). A TZID is converted; a floating time is read in the time
  zone passed in (the importer's own).
- COMPLETED (or STATUS:COMPLETED / CANCELLED) puts the task in the workspace's
  first done status, keeping the completion time from the file. Other tasks
  go in the default status for new tasks.
- RRULE:FREQ=DAILY or WEEKLY with an INTERVAL becomes recurrence_days, and
  X-VTODO-RECUR-FROM:COMPLETION sets recurrence_from. A rule vTodo can't
  represent (BYDAY=MO,WE, monthly, ...) still imports the task, as a one-off,
  with a warning. A matched task keeps its own recurrence in that case.
- A completed VTODO says nothing about recurrence: the export drops RRULE from
  the finished copy of a series. A matched task keeps its recurrence then too.
- Importing restores a recorded state rather than doing the work, so
  completing a recurring task this way spawns no next occurrence.
"""

import dataclasses
import datetime
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction

from . import activity, lifecycle
from .ical import ARCHIVED_PROPERTY, DURATION_PROPERTY, RECUR_FROM_PROPERTY

# Big enough for tens of thousands of tasks; small enough to hold in memory
# and to round-trip through the preview form (DATA_UPLOAD_MAX_MEMORY_SIZE).
MAX_BYTES = 2 * 1024 * 1024

TITLE_MAX = 500  # Task.title max_length
SMALL_INT_MAX = 32767  # PositiveSmallIntegerField

CREATE = "create"
UPDATE = "update"
SKIP = "skip"


class IcsImportError(Exception):
    """The file can't be imported at all (as opposed to a per-task warning)."""


# ── Reading the file ──────────────────────────────────────────────────────────


@dataclasses.dataclass
class Property:
    name: str
    params: dict
    value: str


def unfold(text):
    """Content lines with folding undone (RFC 5545 3.1). Accepts LF or CRLF."""
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw.strip():
            lines.append(raw)
    return lines


def _split_unquoted(text, sep):
    parts, current, quoted = [], [], False
    for char in text:
        if char == '"':
            quoted = not quoted
        if char == sep and not quoted:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def parse_line(line):
    """A content line as a Property, or None when it isn't one."""
    quoted = False
    for i, char in enumerate(line):
        if char == '"':
            quoted = not quoted
        elif char == ":" and not quoted:
            head, value = line[:i], line[i + 1 :]
            break
    else:
        return None
    name, *raw_params = _split_unquoted(head, ";")
    params = {}
    for raw in raw_params:
        key, _, val = raw.partition("=")
        params[key.strip().upper()] = val.strip().strip('"')
    return Property(name.strip().upper(), params, value)


def unescape_text(value):
    """Undo TEXT escaping (RFC 5545 3.3.11)."""
    out, i = [], 0
    while i < len(value):
        char = value[i]
        if char == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
        else:
            out.append(char)
            i += 1
    return "".join(out)


def split_text_list(value):
    """A comma-separated list of TEXT values, e.g. CATEGORIES."""
    items, current, i = [], [], 0
    while i < len(value):
        char = value[i]
        if char == "\\" and i + 1 < len(value):
            current.append(value[i : i + 2])
            i += 2
            continue
        if char == ",":
            items.append("".join(current))
            current = []
        else:
            current.append(char)
        i += 1
    items.append("".join(current))
    return [unescape_text(item).strip() for item in items]


def vtodos(text):
    """Each VTODO in the calendar as a list of its Properties. Components
    nested in a VTODO (VALARM) are skipped."""
    stack, todos, current = [], [], None
    seen_calendar = False
    for line in unfold(text):
        prop = parse_line(line)
        if prop is None:
            continue
        if prop.name == "BEGIN":
            component = prop.value.strip().upper()
            if component == "VCALENDAR":
                seen_calendar = True
            if component == "VTODO" and stack == ["VCALENDAR"]:
                current = []
            stack.append(component)
        elif prop.name == "END":
            component = prop.value.strip().upper()
            if stack and stack[-1] == component:
                stack.pop()
                if component == "VTODO" and current is not None and stack == ["VCALENDAR"]:
                    todos.append(current)
                    current = None
        elif current is not None and stack and stack[-1] == "VTODO":
            current.append(prop)
    if not seen_calendar:
        raise IcsImportError("That isn't an iCalendar (.ics) file.")
    return todos


# ── Values ────────────────────────────────────────────────────────────────────

_DATE_RE = re.compile(r"(\d{4})(\d{2})(\d{2})")
_DATETIME_RE = re.compile(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z?)", re.IGNORECASE)
_DURATION_RE = re.compile(
    r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", re.IGNORECASE
)


def _zone(tzid):
    try:
        return ZoneInfo(tzid)
    except (ZoneInfoNotFoundError, ValueError):
        # e.g. "/mozilla.org/20050126_1/America/New_York"
        tail = "/".join(tzid.strip("/").split("/")[-2:])
        try:
            return ZoneInfo(tail)
        except (ZoneInfoNotFoundError, ValueError):
            return None


def parse_when(prop, *, floating_tz, warn):
    """A DATE or DATE-TIME property as a date (no time given) or an aware UTC
    datetime. None when it can't be read."""
    value = prop.value.strip()
    match = _DATE_RE.fullmatch(value)
    if match:
        try:
            return datetime.date(*map(int, match.groups()))
        except ValueError:
            return None
    match = _DATETIME_RE.fullmatch(value)
    if not match:
        return None
    try:
        naive = datetime.datetime(*map(int, match.groups()[:6]))
    except ValueError:
        return None
    if match.group(7):
        zone = datetime.UTC
    elif "TZID" in prop.params:
        zone = _zone(prop.params["TZID"])
        if zone is None:
            warn(f"unknown time zone {prop.params['TZID']!r}, read as UTC")
            zone = datetime.UTC
    else:
        zone = floating_tz
    return naive.replace(tzinfo=zone).astimezone(datetime.UTC)


def parse_duration_minutes(value):
    match = _DURATION_RE.fullmatch(value.strip())
    if not match or not any(match.groups()):
        return None
    weeks, days, hours, minutes, seconds = (int(g or 0) for g in match.groups())
    total = (((weeks * 7 + days) * 24 + hours) * 60) + minutes + (1 if seconds else 0)
    return min(total, SMALL_INT_MAX) or None


def parse_rrule(value):
    """(recurrence_days, problem). recurrence_days is None when the rule
    can't be represented, and problem says why (or notes what was dropped)."""
    parts = {}
    for part in value.strip().split(";"):
        key, _, val = part.partition("=")
        if key:
            parts[key.strip().upper()] = val.strip().upper()
    unit = {"DAILY": 1, "WEEKLY": 7}.get(parts.get("FREQ", ""))
    if unit is None:
        return None, f"repeats {parts.get('FREQ', 'on an unknown schedule').lower()}"
    try:
        interval = int(parts.get("INTERVAL", "1"))
    except ValueError:
        return None, "has an unreadable INTERVAL"
    if interval < 1 or interval * unit > SMALL_INT_MAX:
        return None, "has an out-of-range INTERVAL"
    by_parts = sorted(k for k in parts if k.startswith("BY"))
    weekly_one_day = (
        unit == 7 and by_parts == ["BYDAY"] and re.fullmatch(r"[A-Z]{2}", parts["BYDAY"])
    )
    if by_parts and not weekly_one_day:
        return None, "repeats on specific days (" + ";".join(f"{k}={parts[k]}" for k in by_parts) + ")"
    problem = None
    if "COUNT" in parts or "UNTIL" in parts:
        problem = "its end (COUNT/UNTIL) is dropped; it repeats until you stop it"
    return interval * unit, problem


# ── One VTODO → the task it describes ─────────────────────────────────────────


@dataclasses.dataclass
class Incoming:
    uid: str | None
    title: str
    notes: str = ""
    tags: list = dataclasses.field(default_factory=list)
    due_date: datetime.date | None = None
    due_time: datetime.time | None = None
    duration_minutes: int | None = None
    # None with recurrence_known=False: leave a matched task's recurrence alone.
    recurrence_days: int | None = None
    recurrence_from: str | None = None
    recurrence_known: bool = True
    done: bool = False
    completed_at: datetime.datetime | None = None
    is_archived: bool = False
    created_at: datetime.datetime | None = None
    is_override: bool = False  # a RECURRENCE-ID instance of another VTODO


def read_vtodo(props, *, floating_tz, warnings):
    from .models import Task

    first = {}
    categories = []
    for prop in props:
        first.setdefault(prop.name, prop)
        if prop.name == "CATEGORIES":
            categories.extend(split_text_list(prop.value))

    title = unescape_text(first["SUMMARY"].value).strip() if "SUMMARY" in first else ""
    label = title or "(untitled)"

    def warn(message):
        warnings.append(f'"{label}": {message}.')

    if not title:
        title = "Untitled task"
        warn("it has no title, so it's called “Untitled task”")
    elif len(title) > TITLE_MAX:
        title = title[: TITLE_MAX - 1] + "…"
        warn(f"its title is cut to {TITLE_MAX} characters")

    uid = first["UID"].value.strip() if "UID" in first else ""
    item = Incoming(uid=uid[:255] or None, title=title, is_override="RECURRENCE-ID" in first)
    if "DESCRIPTION" in first:
        item.notes = unescape_text(first["DESCRIPTION"].value).replace("\r\n", "\n")
    item.tags = list(dict.fromkeys(t for t in categories if t))

    if "DUE" in first:
        due = parse_when(first["DUE"], floating_tz=floating_tz, warn=warn)
        if due is None:
            warn("its due date can't be read, so it's left off")
        elif isinstance(due, datetime.datetime):
            item.due_date, item.due_time = due.date(), due.time()
        else:
            item.due_date = due

    status = first["STATUS"].value.strip().upper() if "STATUS" in first else ""
    item.done = "COMPLETED" in first or status in ("COMPLETED", "CANCELLED")
    if "COMPLETED" in first:
        when = parse_when(first["COMPLETED"], floating_tz=floating_tz, warn=warn)
        if isinstance(when, datetime.date) and not isinstance(when, datetime.datetime):
            when = datetime.datetime.combine(when, datetime.time(), tzinfo=datetime.UTC)
        item.completed_at = when

    if "CREATED" in first:
        when = parse_when(first["CREATED"], floating_tz=floating_tz, warn=warn)
        if isinstance(when, datetime.datetime):
            item.created_at = when

    if "RRULE" in first:
        days, problem = parse_rrule(first["RRULE"].value)
        if days is None:
            warn(f"it {problem}, which vTodo can't repeat, so it comes in as a one-off task")
            item.recurrence_known = False
        else:
            if problem:
                warn(problem)
            item.recurrence_days = days
            recur_from = first.get(RECUR_FROM_PROPERTY)
            item.recurrence_from = (
                Task.RECURRENCE_FROM_COMPLETION
                if recur_from and recur_from.value.strip().upper() == "COMPLETION"
                else Task.RECURRENCE_FROM_DUE_DATE
            )
    elif item.done:
        item.recurrence_known = False

    if DURATION_PROPERTY in first:
        item.duration_minutes = parse_duration_minutes(first[DURATION_PROPERTY].value)
    if ARCHIVED_PROPERTY in first:
        item.is_archived = first[ARCHIVED_PROPERTY].value.strip().upper() == "TRUE"
    return item


def user_zone(user):
    """The time zone a floating time in the file is read in: the user's."""
    return _zone(getattr(user, "timezone", "") or "UTC") or datetime.UTC


# ── Planning and applying ─────────────────────────────────────────────────────


@dataclasses.dataclass
class PlannedTask:
    action: str
    title: str
    uid: str | None
    changes: list = dataclasses.field(default_factory=list)
    reason: str = ""

    @property
    def change_labels(self):
        return [c.replace("_", " ") for c in self.changes]

    def as_dict(self):
        return {
            "action": self.action,
            "title": self.title,
            "uid": self.uid,
            "changes": self.changes,
            "reason": self.reason,
        }


@dataclasses.dataclass
class ImportResult:
    dry_run: bool
    tasks: list
    warnings: list

    def _count(self, action):
        return sum(1 for t in self.tasks if t.action == action)

    @property
    def created(self):
        return self._count(CREATE)

    @property
    def updated(self):
        return self._count(UPDATE)

    @property
    def skipped(self):
        return self._count(SKIP)

    @property
    def summary(self):
        return f"{self.created} new, {self.updated} updated, {self.skipped} skipped"

    def as_dict(self):
        return {
            "dry_run": self.dry_run,
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "summary": self.summary,
            "warnings": self.warnings,
            "tasks": [t.as_dict() for t in self.tasks],
        }


def _seconds(dt):
    return dt.replace(microsecond=0) if dt else None


def _norm_notes(notes):
    return (notes or "").replace("\r\n", "\n")


def _field_changes(task, item):
    """{field: new value} for the plain fields that differ."""
    wanted = {
        "title": item.title,
        "notes": item.notes,
        "tags": item.tags,
        "due_date": item.due_date,
        "due_time": item.due_time,
        "duration_minutes": item.duration_minutes,
        "is_archived": item.is_archived,
    }
    if item.recurrence_known:
        wanted["recurrence_days"] = item.recurrence_days
        if item.recurrence_days:
            wanted["recurrence_from"] = item.recurrence_from
    changes = {}
    for field, value in wanted.items():
        current = getattr(task, field)
        if field == "notes":
            same = _norm_notes(current) == _norm_notes(value)
        elif field == "tags":
            same = list(current or []) == list(value)
        else:
            same = current == value
        if not same:
            changes[field] = value
    return changes


def _completion_changes(task, item):
    """Whether the task's done-ness or completion time differs from the file."""
    is_done = task.completed_at is not None
    if item.done != is_done:
        return True
    return bool(item.done and item.completed_at and _seconds(task.completed_at) != _seconds(item.completed_at))


class _Statuses:
    def __init__(self, workspace, user):
        from .models import TaskStatus
        from .selectors import default_status_slug

        statuses = list(TaskStatus.objects.filter(workspace=workspace).order_by("order", "pk"))
        self.by_slug = {s.slug: s for s in statuses}
        done = [s for s in statuses if s.is_done]
        open_ = [s for s in statuses if not s.is_done]
        self.done_slug = done[0].slug if done else None
        default = default_status_slug(user) if user is not None else None
        if default in self.by_slug and not self.by_slug[default].is_done:
            self.open_slug = default
        else:
            self.open_slug = open_[0].slug if open_ else "todo"

    def reopen_slug(self, task):
        prev = self.by_slug.get(task.previous_status)
        return prev.slug if prev and not prev.is_done else self.open_slug


def plan(items, existing, *, warnings):
    """What importing `items` into a workspace whose tasks by UID are
    `existing` would do: a PlannedTask per item, in file order."""
    planned, seen = [], set()
    for item in items:
        if item.is_override:
            warnings.append(
                f'"{item.title}": it changes one occurrence of a repeating task, which vTodo '
                "doesn't keep separately, so it's skipped."
            )
            planned.append(PlannedTask(SKIP, item.title, item.uid, reason="one occurrence of a repeating task"))
            continue
        if item.uid and item.uid in seen:
            warnings.append(f'"{item.title}": its UID appears earlier in the file, so it\'s skipped.')
            planned.append(PlannedTask(SKIP, item.title, item.uid, reason="duplicate UID"))
            continue
        if item.uid:
            seen.add(item.uid)
        task = existing.get(item.uid) if item.uid else None
        if task is None:
            if not item.uid:
                warnings.append(
                    f'"{item.title}": it has no UID, so importing this file again will add it again.'
                )
            planned.append(PlannedTask(CREATE, item.title, item.uid))
            continue
        changes = list(_field_changes(task, item))
        if _completion_changes(task, item):
            changes.append("done" if item.done else "reopened")
        if changes:
            planned.append(PlannedTask(UPDATE, item.title, item.uid, changes=changes))
        else:
            planned.append(PlannedTask(SKIP, item.title, item.uid, reason="already up to date"))
    return planned


def _apply_completion(task, item, statuses, *, user, source, record):
    """Put `task` where the file says (done or open) without spawning a
    recurrence. Returns True when its status changed."""
    from .models import TaskActivity

    is_done = task.completed_at is not None
    before = task.status
    if item.done:
        slug = task.status if is_done else statuses.done_slug
        lifecycle.restore(task, slug, to_done=True, completed_at=item.completed_at)
    elif is_done or task.pk is None:
        slug = statuses.reopen_slug(task) if is_done else statuses.open_slug
        lifecycle.restore(task, slug, to_done=False)
    if record and before != task.status:
        activity.record(
            task, TaskActivity.MOVED, actor=user, source=source,
            field="status", old=before, new=task.status,
        )
    return before != task.status


def import_ics(text, *, workspace, user, dry_run=True, source="web", floating_tz=None):
    """Import the VTODOs in `text` into `workspace` as `user`. With dry_run,
    nothing is written. Raises IcsImportError when the file can't be read."""
    from .models import Task

    if len(text.encode("utf-8")) > MAX_BYTES:
        raise IcsImportError(f"That file is too big. The limit is {MAX_BYTES // (1024 * 1024)} MB.")
    floating_tz = floating_tz or datetime.UTC
    warnings = []
    items = [read_vtodo(props, floating_tz=floating_tz, warnings=warnings) for props in vtodos(text)]
    uids = [i.uid for i in items if i.uid]
    existing = {t.ical_uid: t for t in Task.objects.filter(workspace=workspace, ical_uid__in=uids)}

    statuses = _Statuses(workspace, user)
    if statuses.done_slug is None and any(i.done for i in items):
        warnings.append(
            f"{workspace.name} has no done status, so completed tasks come in as open."
        )
        for item in items:
            item.done, item.completed_at = False, None
    planned = plan(items, existing, warnings=warnings)
    result = ImportResult(dry_run=dry_run, tasks=planned, warnings=warnings)
    if dry_run:
        return result

    with transaction.atomic():
        order = Task.objects.filter(workspace=workspace).count()
        for item, step in zip(items, planned, strict=True):
            if step.action == CREATE:
                _create(item, workspace=workspace, user=user, order=order, statuses=statuses, source=source)
                order += 1
            elif step.action == UPDATE:
                _update(existing[item.uid], item, user=user, statuses=statuses, source=source)
    return result


def _create(item, *, workspace, user, order, statuses, source):
    from .models import Task

    task = Task(
        user=user,
        workspace=workspace,
        title=item.title,
        notes=item.notes,
        tags=item.tags,
        due_date=item.due_date,
        due_time=item.due_time,
        duration_minutes=item.duration_minutes,
        recurrence_days=item.recurrence_days,
        is_archived=item.is_archived,
        order=order,
        status="",
    )
    if item.uid:
        task.ical_uid = item.uid
    if item.recurrence_from:
        task.recurrence_from = item.recurrence_from
    _apply_completion(task, item, statuses, user=user, source=source, record=False)
    task.save()
    if item.created_at:
        Task.objects.filter(pk=task.pk).update(created_at=item.created_at)
        task.created_at = item.created_at
    activity.record_created(task, actor=user, source=source)
    return task


def _update(task, item, *, user, statuses, source):
    before = activity.snapshot(task)
    for field, value in _field_changes(task, item).items():
        setattr(task, field, value)
    task.save()
    activity.record_changes(task, before, actor=user, source=source)
    if _completion_changes(task, item):
        _apply_completion(task, item, statuses, user=user, source=source, record=True)
        task.save(update_fields=lifecycle.ENTER_STATUS_FIELDS + ["updated_at"])
    return task
