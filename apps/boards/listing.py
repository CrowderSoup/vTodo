"""Ordering and grouping tasks for the list view.

Done tasks always go below open ones: within each group, whatever the sort.
A task is done when it has `completed_at` (TaskState.DONE; archived tasks
never reach the list).
"""

from datetime import timedelta

from .filtering import GROUP_NONE, SORT_DESC

NO_DUE_DATE_LABEL = "No due date"


def _manual_key(task):
    return (task.order, task.created_at)


def _assignee_name(task):
    assignee = task.assignee
    return (assignee.display_name or assignee.username).casefold() if assignee else None


def _sort_value(task, sort, status_rank):
    """The value a task sorts by, or None when it has none (no due date, nobody
    assigned). Those go last in either direction."""
    if sort == "due":
        if task.due_date is None:
            return None
        # A date with no time comes before the same date with a time, as on the calendar.
        return (task.due_date, task.due_time is not None, task.due_time or "")
    if sort == "status":
        return status_rank.get(task.status)
    if sort == "assignee":
        return _assignee_name(task)
    if sort == "title":
        return task.title.casefold()
    if sort == "created":
        return task.created_at
    if sort == "updated":
        return task.updated_at
    return _manual_key(task)


def sort_tasks(tasks, sort, sort_dir, statuses):
    """Open tasks in the chosen order, then done tasks in the same order. Ties,
    and tasks with nothing to sort by, keep the board's order."""
    status_rank = {status.slug: rank for rank, status in enumerate(statuses)}
    descending = sort_dir == SORT_DESC

    def ordered(group):
        group = sorted(group, key=_manual_key)
        valued = [t for t in group if _sort_value(t, sort, status_rank) is not None]
        missing = [t for t in group if _sort_value(t, sort, status_rank) is None]
        # sorted() is stable, so equal values keep the manual order above.
        valued.sort(key=lambda t: _sort_value(t, sort, status_rank), reverse=descending)
        return valued + missing

    open_tasks = [t for t in tasks if not t.completed_at]
    done_tasks = [t for t in tasks if t.completed_at]
    return ordered(open_tasks) + ordered(done_tasks)


def _due_bucket(task, today):
    if task.completed_at:
        # A finished task isn't overdue or due today any more.
        return "done"
    if task.due_date is None:
        return "none"
    if task.due_date < today:
        return "overdue"
    if task.due_date == today:
        return "today"
    if task.due_date <= today + timedelta(days=7):
        return "this_week"
    return "later"


DUE_GROUPS = (
    ("overdue", "Overdue"),
    ("today", "Today"),
    ("this_week", "Next 7 days"),
    ("later", "Later"),
    ("none", NO_DUE_DATE_LABEL),
    ("done", "Done"),
)


def _group(group, value, label, tasks, color=""):
    return {"key": f"{group}:{value}", "label": label, "color": color, "tasks": tasks}


def group_tasks(tasks, group, *, statuses, viewer, today):
    """`tasks` (already sorted) split into groups, in display order. Each group
    is {key, label, color, tasks}; `key` is what collapsing a group stores.
    Empty groups are left out. With no grouping there is one group, labelled ""."""
    if group == "status":
        known = {status.slug for status in statuses}
        groups = [
            _group("status", status.slug, status.name, [t for t in tasks if t.status == status.slug], status.color)
            for status in statuses
        ]
        groups.append(_group("status", "", "No status", [t for t in tasks if t.status not in known]))
    elif group == "assignee":
        people = {}
        for task in tasks:
            if task.assignee_id is not None:
                people.setdefault(task.assignee_id, task.assignee)
        # The person looking first, then everyone else by name.
        order = sorted(
            people.values(),
            key=lambda u: (u.pk != viewer.pk, (u.display_name or u.username).casefold()),
        )
        groups = [
            _group(
                "assignee", person.pk,
                "Me" if person.pk == viewer.pk else (person.display_name or person.username),
                [t for t in tasks if t.assignee_id == person.pk],
            )
            for person in order
        ]
        groups.append(_group("assignee", "", "Unassigned", [t for t in tasks if t.assignee_id is None]))
    elif group == "due":
        buckets = {}
        for task in tasks:
            buckets.setdefault(_due_bucket(task, today), []).append(task)
        groups = [_group("due", value, label, buckets.get(value, [])) for value, label in DUE_GROUPS]
    elif group == "tag":
        # A task with two tags is in both groups.
        tags = sorted({tag for task in tasks for tag in task.tags}, key=str.casefold)
        groups = [_group("tag", tag, tag, [t for t in tasks if tag in t.tags]) for tag in tags]
        groups.append(_group("tag", "", "Untagged", [t for t in tasks if not t.tags]))
    else:
        return [_group(GROUP_NONE, "", "", list(tasks))]
    return [g for g in groups if g["tasks"]]
