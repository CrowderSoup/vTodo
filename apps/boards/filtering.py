"""The task filter the board, the calendar and the list share.

A person's filter lives in their session, one per board: the tags a task must
have, the tags it must not, a due-date window, a search query, and which lanes
are collapsed. Every view reads it through `board_filter_for` and writes it
through `save_board_filter`, so a filter set on one view applies on the others.
A SavedFilter stores the same shape in `filter_config`.
"""

from dataclasses import dataclass, replace
from datetime import timedelta

from django.utils import timezone

DUE_OVERDUE = "overdue"
DUE_TODAY = "today"
DUE_THIS_WEEK = "this_week"
DUE_CHOICES = (DUE_OVERDUE, DUE_TODAY, DUE_THIS_WEEK)

SESSION_KEY = "board_filter"


def lane_key(kind, pk):
    """A board lane is either a TaskStatus (the default, implicit lane) or a
    Column (an opt-in custom/filtered lane). Both are addressed uniformly -- for
    reorder, hide, archive, and create-in-lane -- via a "kind:pk" key, since
    status and column primary keys come from different tables and can collide."""
    return f"{kind}:{pk}"


def parse_lane_key(key):
    """(kind, pk) for a lane key, or (None, None) if it isn't one."""
    kind, _, pk = (key or "").partition(":")
    if kind not in ("status", "column") or not pk.isdigit():
        return None, None
    return kind, int(pk)


def due_matches(due, due_date, today):
    """Whether a task due on `due_date` falls in the `due` window. An empty or
    unknown window matches everything."""
    if due == DUE_OVERDUE:
        return bool(due_date) and due_date < today
    if due == DUE_TODAY:
        return due_date == today
    if due == DUE_THIS_WEEK:
        return bool(due_date) and today <= due_date <= today + timedelta(days=7)
    return True


def task_matches_column(task, filter_config, today=None):
    """Whether a task belongs in a custom Column lane. A column's tags match on
    any one tag, unlike the person's filter, which needs all of them."""
    statuses = filter_config.get("statuses") or []
    tags = filter_config.get("tags") or []
    if statuses and task.status not in statuses:
        return False
    if tags and not any(t in task.tags for t in tags):
        return False
    return due_matches(filter_config.get("due"), task.due_date, today or timezone.localdate())


def _clean_list(values):
    """Strings from a stored or posted list, stripped, blanks and repeats
    dropped, first-seen order kept (the pills show them in that order)."""
    seen = []
    for value in values or []:
        value = str(value).strip()
        if value and value not in seen:
            seen.append(value)
    return tuple(seen)


@dataclass(frozen=True)
class TaskFilter:
    tags: tuple = ()
    exclude_tags: tuple = ()
    due: str = ""
    q: str = ""
    hidden_lanes: tuple = ()

    @classmethod
    def from_config(cls, config):
        """A filter from a session or SavedFilter dict. Anything malformed or
        unknown is dropped rather than trusted."""
        config = config if isinstance(config, dict) else {}
        due = str(config.get("due") or "").strip()
        return cls(
            tags=_clean_list(config.get("tags")),
            exclude_tags=_clean_list(config.get("exclude_tags")),
            due=due if due in DUE_CHOICES else "",
            q=str(config.get("q") or "").strip(),
            hidden_lanes=tuple(
                key for key in _clean_list(config.get("hidden_lanes")) if parse_lane_key(key)[0]
            ),
        )

    @classmethod
    def from_post(cls, post):
        """A filter from the filter bar's form."""
        return cls.from_config({
            "tags": post.getlist("tags"),
            "exclude_tags": post.getlist("exclude_tags"),
            "due": post.get("due", ""),
            "q": post.get("q", ""),
            "hidden_lanes": post.getlist("hidden_lanes"),
        })

    def to_config(self):
        return {
            "tags": list(self.tags),
            "exclude_tags": list(self.exclude_tags),
            "due": self.due,
            "q": self.q,
            "hidden_lanes": list(self.hidden_lanes),
        }

    def replace(self, **changes):
        return replace(self, **changes)

    def including_tag(self, tag):
        """Also require `tag`. It stops being excluded if it was."""
        tag = tag.strip()
        if not tag:
            return self
        return self.replace(
            tags=self.tags if tag in self.tags else self.tags + (tag,),
            exclude_tags=tuple(t for t in self.exclude_tags if t != tag),
        )

    def excluding_tag(self, tag):
        """Also hide tasks tagged `tag`. It stops being required if it was."""
        tag = tag.strip()
        if not tag:
            return self
        return self.replace(
            tags=tuple(t for t in self.tags if t != tag),
            exclude_tags=self.exclude_tags if tag in self.exclude_tags else self.exclude_tags + (tag,),
        )

    def toggling_lane(self, key):
        """Collapse the lane if it's open, open it if it's collapsed."""
        if key in self.hidden_lanes:
            return self.replace(hidden_lanes=tuple(k for k in self.hidden_lanes if k != key))
        return self.replace(hidden_lanes=self.hidden_lanes + (key,))

    @property
    def active_count(self):
        """How many filters are on, for the badge on the Filters button."""
        return (
            len(self.tags) + len(self.exclude_tags) + len(self.hidden_lanes)
            + bool(self.due) + bool(self.q)
        )

    def matches(self, task, today):
        """Whether a task passes the tag, due and search filters. Collapsed lanes
        are left to the caller: on the board a collapsed lane still shows its
        count, and only the views that know the lanes can tell which a task is in."""
        if self.tags and not all(tag in task.tags for tag in self.tags):
            return False
        if self.exclude_tags and any(tag in task.tags for tag in self.exclude_tags):
            return False
        if not due_matches(self.due, task.due_date, today):
            return False
        if self.q:
            query = self.q.lower()
            if query not in task.title.lower() and query not in task.notes.lower():
                return False
        return True

    def apply(self, tasks, today=None):
        today = today or timezone.localdate()
        return [task for task in tasks if self.matches(task, today)]

    def _identity(self):
        # Order doesn't make two filters different.
        return (
            sorted(self.tags), sorted(self.exclude_tags), self.due, self.q, sorted(self.hidden_lanes),
        )

    def same_as(self, other):
        return self._identity() == other._identity()

    def matching_saved_filter(self, saved_filters):
        """The SavedFilter whose config is this filter, if any: the saved-view
        select shows it as chosen."""
        for saved in saved_filters:
            if self.same_as(TaskFilter.from_config(saved.filter_config)):
                return saved
        return None


def board_filter_for(board, session):
    """This board's filter from the session. Empty when there's none."""
    all_filters = (session.get(SESSION_KEY) or {}) if session else {}
    return TaskFilter.from_config(all_filters.get(str(board.pk)))


def save_board_filter(request, board, task_filter):
    all_filters = request.session.get(SESSION_KEY) or {}
    all_filters[str(board.pk)] = task_filter.to_config()
    request.session[SESSION_KEY] = all_filters
    request.session.modified = True
