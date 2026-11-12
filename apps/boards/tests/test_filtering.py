from datetime import date, timedelta
from types import SimpleNamespace

from django.http import QueryDict

from apps.boards.filtering import (
    BOARD_IGNORES,
    CALENDAR_IGNORES,
    TaskFilter,
    board_filter_for,
    due_matches,
    parse_lane_key,
    task_matches_column,
)

TODAY = date(2026, 3, 10)


def _task(title="Task", notes="", tags=(), due_date=None, status="todo"):
    return SimpleNamespace(title=title, notes=notes, tags=list(tags), due_date=due_date, status=status)


def test_empty_filter_matches_everything():
    tasks = [_task(), _task(tags=["home"], due_date=TODAY)]
    assert TaskFilter().apply(tasks, TODAY) == tasks
    assert TaskFilter().active_count() == 0


def test_tags_must_all_match_and_excluded_tags_must_all_be_absent():
    both = _task(tags=["home", "chore"])
    home = _task(tags=["home"])
    errand = _task(tags=["home", "errand"])
    task_filter = TaskFilter(tags=("home", "chore"))
    assert task_filter.apply([both, home, errand], TODAY) == [both]
    assert TaskFilter(exclude_tags=("errand",)).apply([both, home, errand], TODAY) == [both, home]


def test_search_looks_at_title_and_notes_ignoring_case():
    by_title = _task(title="Buy MILK")
    by_notes = _task(title="Groceries", notes="milk, eggs")
    other = _task(title="Laundry")
    assert TaskFilter(q="milk").apply([by_title, by_notes, other], TODAY) == [by_title, by_notes]


def test_due_windows():
    yesterday, tomorrow = TODAY - timedelta(days=1), TODAY + timedelta(days=1)
    week_out, past_week = TODAY + timedelta(days=7), TODAY + timedelta(days=8)
    assert due_matches("overdue", yesterday, TODAY)
    assert not due_matches("overdue", TODAY, TODAY)
    assert not due_matches("overdue", None, TODAY)
    assert due_matches("today", TODAY, TODAY)
    assert not due_matches("today", tomorrow, TODAY)
    assert due_matches("this_week", TODAY, TODAY)
    assert due_matches("this_week", week_out, TODAY)
    assert not due_matches("this_week", past_week, TODAY)
    assert not due_matches("this_week", yesterday, TODAY)
    assert due_matches("", None, TODAY)


def test_from_config_drops_junk():
    task_filter = TaskFilter.from_config({
        "tags": [" home ", "", "home", "chore"],
        "exclude_tags": None,
        "due": "next_year",
        "q": "  milk ",
        "hidden_lanes": ["status:3", "nonsense", "column:x", "column:4"],
        "unknown": "ignored",
    })
    assert task_filter == TaskFilter(
        tags=("home", "chore"), q="milk", hidden_lanes=("status:3", "column:4")
    )
    assert TaskFilter.from_config(None) == TaskFilter()
    assert TaskFilter.from_config("not a dict") == TaskFilter()


def test_config_round_trip():
    task_filter = TaskFilter(
        tags=("a",), exclude_tags=("b",), due="today", q="x", hidden_lanes=("status:1",),
        show_done=False, sort="due", sort_dir="desc", group="status", collapsed_groups=("status:done",),
    )
    assert TaskFilter.from_config(task_filter.to_config()) == task_filter


def test_old_configs_get_the_default_layout():
    task_filter = TaskFilter.from_config({"tags": ["home"]})
    assert (task_filter.show_done, task_filter.sort, task_filter.sort_dir, task_filter.group) == (
        True, "manual", "asc", "none",
    )
    junk = TaskFilter.from_config({"sort": "colour", "sort_dir": "up", "group": "mood", "show_done": "no"})
    assert (junk.sort, junk.sort_dir, junk.group, junk.show_done) == ("manual", "asc", "none", True)


def test_layout_form_changes_only_what_it_sends():
    before = TaskFilter(tags=("home",), sort="due", group="tag", collapsed_groups=("tag:a",))
    post = QueryDict(mutable=True)
    post["sort_dir"] = "desc"
    after = before.with_layout_from(post)
    assert after == before.replace(sort_dir="desc")


def test_changing_the_grouping_forgets_collapsed_groups():
    before = TaskFilter(group="tag", collapsed_groups=("tag:a",))
    post = QueryDict(mutable=True)
    post["group"] = "status"
    assert before.with_layout_from(post) == TaskFilter(group="status")


def test_toggling_a_group():
    task_filter = TaskFilter().toggling_group("tag:home")
    assert task_filter.collapsed_groups == ("tag:home",)
    assert task_filter.toggling_group("tag:home").collapsed_groups == ()


def test_filter_bar_form_replaces_the_filters_and_keeps_the_layout():
    post = QueryDict(mutable=True)
    post.setlist("tags", ["home"])
    post.setlist("exclude_tags", ["work"])
    post.setlist("hidden_lanes", ["status:2"])
    post["due"] = "overdue"
    post["q"] = "milk"
    before = TaskFilter(tags=("old",), q="old", sort="due", group="tag", collapsed_groups=("tag:a",))
    assert before.with_filters_from(post) == TaskFilter(
        tags=("home",), exclude_tags=("work",), due="overdue", q="milk", hidden_lanes=("status:2",),
        sort="due", group="tag", collapsed_groups=("tag:a",),
    )


def test_show_done_from_the_filter_bar():
    def posted(*values):
        post = QueryDict(mutable=True)
        post.setlist("show_done", list(values))
        return TaskFilter(show_done=False).with_filters_from(post).show_done

    assert posted() is True  # Clear filters sends nothing: back to showing them
    assert posted("0") is False  # hidden input carrying the current value
    assert posted("1") is True
    assert posted("0", "1") is True  # hidden "0" then the ticked checkbox



def test_including_and_excluding_a_tag_move_it_between_lists():
    task_filter = TaskFilter(tags=("home",), exclude_tags=("work",))
    assert task_filter.including_tag("work") == TaskFilter(tags=("home", "work"))
    assert task_filter.excluding_tag("home") == TaskFilter(exclude_tags=("work", "home"))
    assert task_filter.including_tag("home") == task_filter
    assert task_filter.including_tag("  ") == task_filter


def test_toggling_a_lane():
    task_filter = TaskFilter().toggling_lane("status:1")
    assert task_filter.hidden_lanes == ("status:1",)
    assert task_filter.toggling_lane("status:1").hidden_lanes == ()


def test_active_count_counts_filters_but_not_layout():
    task_filter = TaskFilter(
        tags=("a", "b"), exclude_tags=("c",), due="today", q="x", hidden_lanes=("status:1",),
        show_done=False, sort="title", group="tag",
    )
    assert task_filter.active_count() == 7
    assert task_filter.active_count(ignore=CALENDAR_IGNORES) == 4


def test_saved_filter_matching_ignores_fields_the_view_does_not_use():
    saved = [SimpleNamespace(name="Week", filter_config={"due": "this_week", "group": "due"})]
    current = TaskFilter(group="tag")
    assert current.matching_saved_filter(saved) is None
    assert current.matching_saved_filter(saved, ignore=CALENDAR_IGNORES).name == "Week"
    assert TaskFilter(due="this_week").matching_saved_filter(saved, ignore=BOARD_IGNORES).name == "Week"


def test_saved_filter_matches_regardless_of_order():
    saved = [
        SimpleNamespace(name="Other", filter_config={"tags": ["x"]}),
        SimpleNamespace(name="Home", filter_config={"tags": ["chore", "home"], "due": "today"}),
    ]
    assert TaskFilter(tags=("home", "chore"), due="today").matching_saved_filter(saved).name == "Home"
    assert TaskFilter(tags=("home",)).matching_saved_filter(saved) is None


def test_board_filter_for_reads_this_boards_slice_of_the_session():
    board = SimpleNamespace(pk=7)
    session = {"board_filter": {"7": {"tags": ["home"]}, "8": {"tags": ["work"]}}}
    assert board_filter_for(board, session) == TaskFilter(tags=("home",))
    assert board_filter_for(board, {}) == TaskFilter()
    assert board_filter_for(board, None) == TaskFilter()


def test_column_tags_match_on_any_tag():
    task = _task(tags=["home"], status="todo", due_date=TODAY)
    assert task_matches_column(task, {"tags": ["home", "work"]}, TODAY)
    assert not task_matches_column(task, {"statuses": ["done"]}, TODAY)
    assert task_matches_column(task, {"due": "today"}, TODAY)
    assert not task_matches_column(task, {"due": "overdue"}, TODAY)


def test_parse_lane_key():
    assert parse_lane_key("status:3") == ("status", 3)
    assert parse_lane_key("column:12") == ("column", 12)
    assert parse_lane_key("lane:1") == (None, None)
    assert parse_lane_key("status:x") == (None, None)
    assert parse_lane_key(None) == (None, None)
