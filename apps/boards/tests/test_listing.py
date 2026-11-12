from datetime import date, datetime, time, timedelta, timezone
from itertools import count
from types import SimpleNamespace

from apps.boards.listing import group_tasks, sort_tasks

TODAY = date(2026, 3, 10)
_ids = count(1)

ME = SimpleNamespace(pk=1, display_name="Aaron", username="aaron")
AZURE = SimpleNamespace(pk=2, display_name="Azure", username="azure")
BOT = SimpleNamespace(pk=3, display_name="", username="bot")

STATUSES = [
    SimpleNamespace(slug="todo", name="To Do", color="#111111"),
    SimpleNamespace(slug="doing", name="Doing", color=""),
    SimpleNamespace(slug="done", name="Done", color=""),
]


def _task(title, *, order=0, status="todo", due_date=None, due_time=None, tags=(), assignee=None,
          done=False, created=0, updated=0):
    pk = next(_ids)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return SimpleNamespace(
        pk=pk, title=title, order=order, status=status, due_date=due_date, due_time=due_time,
        tags=list(tags), assignee=assignee, assignee_id=assignee.pk if assignee else None,
        completed_at=base if done else None,
        created_at=base + timedelta(minutes=created), updated_at=base + timedelta(minutes=updated),
    )


def _titles(tasks):
    return [t.title for t in tasks]


def test_manual_sort_is_board_order_with_done_last():
    a = _task("a", order=2)
    b = _task("b", order=0, done=True)
    c = _task("c", order=1)
    assert _titles(sort_tasks([a, b, c], "manual", "asc", STATUSES)) == ["c", "a", "b"]


def test_done_tasks_stay_last_in_either_direction():
    tasks = [_task("open b"), _task("done a", done=True), _task("open a"), _task("done b", done=True)]
    assert _titles(sort_tasks(tasks, "title", "asc", STATUSES)) == ["open a", "open b", "done a", "done b"]
    assert _titles(sort_tasks(tasks, "title", "desc", STATUSES)) == ["open b", "open a", "done b", "done a"]


def test_due_sort_puts_tasks_without_a_date_last_both_ways():
    later = _task("later", due_date=TODAY + timedelta(days=3))
    soon = _task("soon", due_date=TODAY)
    undated = _task("undated")
    assert _titles(sort_tasks([undated, later, soon], "due", "asc", STATUSES)) == ["soon", "later", "undated"]
    assert _titles(sort_tasks([undated, later, soon], "due", "desc", STATUSES)) == ["later", "soon", "undated"]


def test_due_sort_puts_all_day_before_timed_on_the_same_day():
    timed = _task("3pm", due_date=TODAY, due_time=time(15))
    morning = _task("9am", due_date=TODAY, due_time=time(9))
    all_day = _task("all day", due_date=TODAY)
    assert _titles(sort_tasks([timed, morning, all_day], "due", "asc", STATUSES)) == ["all day", "9am", "3pm"]


def test_status_sort_follows_the_workflow_order():
    tasks = [_task("doing", status="doing"), _task("todo", status="todo"), _task("gone", status="deleted")]
    assert _titles(sort_tasks(tasks, "status", "asc", STATUSES)) == ["todo", "doing", "gone"]


def test_assignee_sort_by_name_with_unassigned_last():
    tasks = [_task("none"), _task("bot", assignee=BOT), _task("aaron", assignee=ME)]
    assert _titles(sort_tasks(tasks, "assignee", "asc", STATUSES)) == ["aaron", "bot", "none"]


def test_created_and_updated_sorts():
    old = _task("old", created=1, updated=9)
    new = _task("new", created=5, updated=2)
    assert _titles(sort_tasks([old, new], "created", "desc", STATUSES)) == ["new", "old"]
    assert _titles(sort_tasks([old, new], "updated", "desc", STATUSES)) == ["old", "new"]


def test_ties_keep_the_manual_order():
    second = _task("same", order=1)
    first = _task("same", order=0)
    assert sort_tasks([second, first], "title", "asc", STATUSES) == [first, second]


def _groups(tasks, group):
    return [
        (g["key"], g["label"], _titles(g["tasks"]))
        for g in group_tasks(tasks, group, statuses=STATUSES, viewer=ME, today=TODAY)
    ]


def test_no_grouping_is_one_unlabelled_group_even_when_empty():
    assert _groups([], "none") == [("none:", "", [])]


def test_group_by_status_in_workflow_order_skipping_empty_ones():
    tasks = [_task("a", status="done", done=True), _task("b", status="todo"), _task("c", status="old")]
    assert _groups(tasks, "status") == [
        ("status:todo", "To Do", ["b"]),
        ("status:done", "Done", ["a"]),
        ("status:", "No status", ["c"]),
    ]


def test_group_by_assignee_puts_me_first_and_unassigned_last():
    tasks = [_task("bot", assignee=BOT), _task("none"), _task("mine", assignee=ME), _task("hers", assignee=AZURE)]
    assert _groups(tasks, "assignee") == [
        ("assignee:1", "Me", ["mine"]),
        ("assignee:2", "Azure", ["hers"]),
        ("assignee:3", "bot", ["bot"]),
        ("assignee:", "Unassigned", ["none"]),
    ]


def test_group_by_due_date_with_done_tasks_on_their_own():
    tasks = [
        _task("late", due_date=TODAY - timedelta(days=1)),
        _task("late but done", due_date=TODAY - timedelta(days=1), done=True),
        _task("today", due_date=TODAY),
        _task("week", due_date=TODAY + timedelta(days=7)),
        _task("later", due_date=TODAY + timedelta(days=8)),
        _task("whenever"),
    ]
    assert _groups(tasks, "due") == [
        ("due:overdue", "Overdue", ["late"]),
        ("due:today", "Today", ["today"]),
        ("due:this_week", "Next 7 days", ["week"]),
        ("due:later", "Later", ["later"]),
        ("due:none", "No due date", ["whenever"]),
        ("due:done", "Done", ["late but done"]),
    ]


def test_group_by_tag_puts_a_task_in_each_of_its_tags():
    tasks = [_task("both", tags=["home", "Chores"]), _task("home", tags=["home"]), _task("bare")]
    assert _groups(tasks, "tag") == [
        ("tag:Chores", "Chores", ["both"]),
        ("tag:home", "home", ["both", "home"]),
        ("tag:", "Untagged", ["bare"]),
    ]


def test_groups_keep_the_sort_order():
    tasks = sort_tasks(
        [_task("b", tags=["x"]), _task("a", tags=["x"]), _task("done", tags=["x"], done=True)],
        "title", "asc", STATUSES,
    )
    assert _groups(tasks, "tag") == [("tag:x", "x", ["a", "b", "done"])]
