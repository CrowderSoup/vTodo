import calendar as calendar_module
import re
from datetime import date, time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.boards.models import Board
from apps.tasks.models import Task
from apps.teams.models import Team, TeamMembership
from apps.users.models import User

from .test_views import _create_team_board, logged_in_client, user_with_board  # noqa: F401


# ---------------------------------------------------------------------------
# CalendarView -- context shape, month math
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_calendar_view_200s_with_expected_context_keys(logged_in_client):
    client, _ = logged_in_client
    response = client.get(reverse("calendar:calendar"))
    assert response.status_code == 200
    for key in (
        "weeks", "undated_tasks", "month_label", "year", "month",
        "prev_year", "prev_month", "next_year", "next_month",
        "today_year", "today_month", "active_filter", "hide_due_filter",
    ):
        assert key in response.context, f"missing context key: {key}"


@pytest.mark.django_db
def test_calendar_view_defaults_to_current_month(logged_in_client):
    client, _ = logged_in_client
    today = timezone.localdate()
    response = client.get(reverse("calendar:calendar"))
    assert response.context["year"] == today.year
    assert response.context["month"] == today.month


@pytest.mark.django_db
def test_calendar_view_honors_year_month_query_params(logged_in_client):
    client, _ = logged_in_client
    response = client.get(reverse("calendar:calendar"), {"year": 2026, "month": 2})
    assert response.context["year"] == 2026
    assert response.context["month"] == 2
    assert response.context["prev_year"] == 2026
    assert response.context["prev_month"] == 1
    assert response.context["next_year"] == 2026
    assert response.context["next_month"] == 3


@pytest.mark.django_db
def test_calendar_view_garbage_month_falls_back_to_today(logged_in_client):
    client, _ = logged_in_client
    today = timezone.localdate()
    response = client.get(reverse("calendar:calendar"), {"year": "nope", "month": "13"})
    assert response.context["year"] == today.year
    assert response.context["month"] == today.month


@pytest.mark.django_db
def test_calendar_row_count_matches_stdlib_month_grid(logged_in_client):
    """weeks length matches calendar.Calendar(firstweekday=6).monthdatescalendar
    (Sunday-start) -- covers both 4/5-row and 6-row months without hardcoding
    which real months those are."""
    client, _ = logged_in_client
    for year, month in ((2026, 2), (2026, 8)):
        expected = calendar_module.Calendar(firstweekday=6).monthdatescalendar(year, month)
        response = client.get(reverse("calendar:calendar"), {"year": year, "month": month})
        assert len(response.context["weeks"]) == len(expected)


@pytest.mark.django_db
def test_calendar_weeks_start_on_sunday(logged_in_client):
    client, _ = logged_in_client
    response = client.get(reverse("calendar:calendar"), {"year": 2026, "month": 4})
    for week in response.context["weeks"]:
        assert week[0]["date"].weekday() == 6  # Sunday
        assert week[-1]["date"].weekday() == 5  # Saturday


@pytest.mark.django_db
def test_task_on_adjacent_month_day_appears_in_its_visible_cell(logged_in_client):
    """A task due on a leading/trailing day from an adjacent month, but still shown
    in the visible grid, appears in that cell (not silently dropped)."""
    client, user = logged_in_client
    weeks = calendar_module.Calendar(firstweekday=6).monthdatescalendar(2026, 4)
    leading_day = weeks[0][0]
    assert leading_day.month != 4  # sanity: actually a leading day from March

    Task.objects.create(user=user, title="Leading day task", status="todo", due_date=leading_day)
    response = client.get(reverse("calendar:calendar"), {"year": 2026, "month": 4})

    first_cell = response.context["weeks"][0][0]
    assert first_cell["date"] == leading_day
    assert first_cell["in_month"] is False
    titles = [t.title for t in first_cell["tasks"]]
    assert "Leading day task" in titles


# ---------------------------------------------------------------------------
# Task bucketing: undated pane, done/overdue, sort order, overflow
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_undated_task_appears_only_in_undated_tasks(logged_in_client):
    client, user = logged_in_client
    today = timezone.localdate()
    Task.objects.create(user=user, title="No date", status="todo")
    dated = Task.objects.create(user=user, title="Has date", status="todo", due_date=today)

    response = client.get(reverse("calendar:calendar"))
    undated_titles = [t.title for t in response.context["undated_tasks"]]
    assert "No date" in undated_titles
    assert "Has date" not in undated_titles

    all_cell_tasks = [t for week in response.context["weeks"] for cell in week for t in cell["tasks"]]
    assert dated in all_cell_tasks


@pytest.mark.django_db
def test_completed_and_overdue_tasks_still_shown(logged_in_client):
    client, user = logged_in_client
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    Task.objects.create(
        user=user, title="Done yesterday", status="done", due_date=yesterday,
        completed_at=timezone.now(),
    )
    Task.objects.create(user=user, title="Overdue open", status="todo", due_date=yesterday)

    response = client.get(reverse("calendar:calendar"))
    all_cell_tasks = [t for week in response.context["weeks"] for cell in week for t in cell["tasks"]]
    titles = [t.title for t in all_cell_tasks]
    assert "Done yesterday" in titles
    assert "Overdue open" in titles


@pytest.mark.django_db
def test_day_sort_order_all_day_before_timed_then_chronological(logged_in_client):
    client, user = logged_in_client
    today = timezone.localdate()
    Task.objects.create(user=user, title="Late timed", status="todo", due_date=today, due_time=time(15, 0))
    Task.objects.create(user=user, title="All day", status="todo", due_date=today)
    Task.objects.create(user=user, title="Early timed", status="todo", due_date=today, due_time=time(9, 0))

    response = client.get(reverse("calendar:calendar"))
    today_cell = next(
        cell for week in response.context["weeks"] for cell in week if cell["date"] == today
    )
    titles = [t.title for t in today_cell["tasks"]]
    assert titles == ["All day", "Early timed", "Late timed"]


@pytest.mark.django_db
def test_day_overflow_truncates_and_counts_remainder(logged_in_client):
    client, user = logged_in_client
    today = timezone.localdate()
    for i in range(5):
        Task.objects.create(user=user, title=f"Task {i}", status="todo", due_date=today)

    response = client.get(reverse("calendar:calendar"))
    today_cell = next(
        cell for week in response.context["weeks"] for cell in week if cell["date"] == today
    )
    assert len(today_cell["tasks"]) == 3
    assert len(today_cell["overflow_tasks"]) == 2
    assert today_cell["overflow_count"] == 2


# ---------------------------------------------------------------------------
# Team scoping
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_calendar_team_route_404s_for_non_member(logged_in_client):
    client, _ = logged_in_client
    team = Team.objects.create(name="Rocketry")
    _create_team_board(team)
    response = client.get(reverse("calendar:calendar-team", args=[team.pk]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_calendar_team_route_shows_teammates_tasks(logged_in_client):
    client, user = logged_in_client
    other = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user)
    TeamMembership.objects.create(team=team, user=other)
    _create_team_board(team)
    today = timezone.localdate()
    Task.objects.create(user=other, team=team, title="Team task", status="todo", due_date=today)

    response = client.get(reverse("calendar:calendar-team", args=[team.pk]))
    all_cell_tasks = [t for week in response.context["weeks"] for cell in week for t in cell["tasks"]]
    assert "Team task" in [t.title for t in all_cell_tasks]


# ---------------------------------------------------------------------------
# Filters shared with board (session-keyed by board.pk)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_calendar_honors_board_session_tag_filter(logged_in_client):
    client, user = logged_in_client
    board = Board.objects.get(user=user)
    today = timezone.localdate()
    Task.objects.create(user=user, title="Tagged", status="todo", due_date=today, tags=["urgent"])
    Task.objects.create(user=user, title="Untagged", status="todo", due_date=today)

    client.post(reverse("boards:board-filter"), {"tags": "urgent", "board_id": board.pk})
    response = client.get(reverse("calendar:calendar"))

    all_cell_tasks = [t for week in response.context["weeks"] for cell in week for t in cell["tasks"]]
    titles = [t.title for t in all_cell_tasks]
    assert "Tagged" in titles
    assert "Untagged" not in titles


@pytest.mark.django_db
def test_calendar_ignores_board_due_filter(logged_in_client):
    """Board's 'due=overdue' session filter is deliberately not applied on
    calendar -- month navigation is calendar's equivalent, so a dated non-overdue
    task must still show even if 'overdue' is the active board filter."""
    client, user = logged_in_client
    board = Board.objects.get(user=user)
    today = timezone.localdate()
    Task.objects.create(user=user, title="Due today", status="todo", due_date=today)

    client.post(reverse("boards:board-filter"), {"due": "overdue", "board_id": board.pk})
    response = client.get(reverse("calendar:calendar"))

    all_cell_tasks = [t for week in response.context["weeks"] for cell in week for t in cell["tasks"]]
    assert "Due today" in [t.title for t in all_cell_tasks]


@pytest.mark.django_db
def test_calendar_excludes_tasks_from_collapsed_lane(logged_in_client):
    """A lane collapsed on the board (LaneHideView) must still hide its tasks
    from the calendar -- collapsing only changes the board's own rendering."""
    from apps.tasks.models import TaskStatus

    client, user = logged_in_client
    status = TaskStatus.objects.get(user=user, team__isnull=True, slug="todo")
    today = timezone.localdate()
    Task.objects.create(user=user, title="In collapsed lane", status="todo", due_date=today)
    Task.objects.create(user=user, title="Elsewhere", status="backlog", due_date=today)

    client.post(reverse("boards:lane-hide", args=[f"status:{status.pk}"]))
    response = client.get(reverse("calendar:calendar"))

    all_cell_tasks = [t for week in response.context["weeks"] for cell in week for t in cell["tasks"]]
    titles = [t.title for t in all_cell_tasks]
    assert "In collapsed lane" not in titles
    assert "Elsewhere" in titles


@pytest.mark.django_db
def test_calendar_honors_board_session_assignee_filter(logged_in_client):
    client, user = logged_in_client
    other = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user)
    TeamMembership.objects.create(team=team, user=other)
    board = _create_team_board(team)
    today = timezone.localdate()
    Task.objects.create(user=user, team=team, title="Mine", status="todo", due_date=today, assignee=user)
    Task.objects.create(user=user, team=team, title="Theirs", status="todo", due_date=today, assignee=other)

    client.post(reverse("boards:board-filter"), {"assignee": "me", "board_id": board.pk})
    response = client.get(reverse("calendar:calendar-team", args=[team.pk]))

    all_cell_tasks = [t for week in response.context["weeks"] for cell in week for t in cell["tasks"]]
    titles = [t.title for t in all_cell_tasks]
    assert "Mine" in titles
    assert "Theirs" not in titles


# ---------------------------------------------------------------------------
# TaskRescheduleView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_reschedule_sets_due_date(logged_in_client):
    client, user = logged_in_client
    task = Task.objects.create(user=user, title="Movable", status="todo")
    new_date = timezone.localdate() + timedelta(days=3)

    response = client.post(
        reverse("calendar:task-reschedule", args=[task.pk]),
        {"due_date": new_date.isoformat()},
    )
    task.refresh_from_db()

    assert response.status_code == 200
    assert task.due_date == new_date


@pytest.mark.django_db
def test_reschedule_empty_string_clears_due_date_and_time(logged_in_client):
    client, user = logged_in_client
    task = Task.objects.create(
        user=user, title="Movable", status="todo",
        due_date=timezone.localdate(), due_time=time(9, 0),
    )

    response = client.post(reverse("calendar:task-reschedule", args=[task.pk]), {"due_date": ""})
    task.refresh_from_db()

    assert response.status_code == 200
    assert task.due_date is None
    assert task.due_time is None


@pytest.mark.django_db
def test_reschedule_malformed_date_returns_422(logged_in_client):
    client, user = logged_in_client
    task = Task.objects.create(user=user, title="Movable", status="todo")

    response = client.post(reverse("calendar:task-reschedule", args=[task.pk]), {"due_date": "not-a-date"})
    assert response.status_code == 422


@pytest.mark.django_db
def test_reschedule_keeps_the_month_being_viewed(logged_in_client):
    """The reschedule POST carries no ?year=&month= of its own -- the response
    must reflect the month named in HX-Current-URL, not silently jump to today's
    month or the new due date's month."""
    client, user = logged_in_client
    task = Task.objects.create(user=user, title="Movable", status="todo", due_date=date(2026, 6, 15))

    response = client.post(
        reverse("calendar:task-reschedule", args=[task.pk]),
        {"due_date": ""},
        HTTP_HX_CURRENT_URL="http://testserver/calendar/?year=2026&month=6",
    )
    assert response.status_code == 200
    assert response.context["year"] == 2026
    assert response.context["month"] == 6


# ---------------------------------------------------------------------------
# Cross-cutting fix: page-aware rendering via HX-Current-URL
# ---------------------------------------------------------------------------


def _calendar_current_url(**params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return f"http://testserver/calendar/?{qs}" if qs else "http://testserver/calendar/"


@pytest.mark.django_db
def test_task_move_from_calendar_page_rerenders_calendar_not_board(logged_in_client):
    client, user = logged_in_client
    task = Task.objects.create(user=user, title="Movable status", status="todo")

    response = client.post(
        reverse("boards:task-move", args=[task.pk]),
        {"new_status": "in_progress"},
        HTTP_HX_CURRENT_URL=_calendar_current_url(year=2026, month=6),
    )
    content = response.content.decode()
    assert response.status_code == 200
    assert "calendar-month-grid" in content
    assert "board-column" not in content


@pytest.mark.django_db
def test_task_move_from_board_page_rerenders_board_not_calendar(logged_in_client):
    client, user = logged_in_client
    task = Task.objects.create(user=user, title="Movable status", status="todo")

    response = client.post(
        reverse("boards:task-move", args=[task.pk]),
        {"new_status": "in_progress"},
        HTTP_HX_CURRENT_URL="http://testserver/board/",
    )
    content = response.content.decode()
    assert response.status_code == 200
    assert "board-column" in content
    assert "calendar-month-grid" not in content


@pytest.mark.django_db
def test_mark_complete_from_panel_on_calendar_page_refreshes_calendar(logged_in_client):
    """Regression test for the bug this refactor targets: the panel's 'Mark
    complete' button posts with hx-target=#task-list-content (not
    #task-panel-content), so it must land in TaskMoveView's non-panel branch --
    which, pre-fix, always re-rendered board columns even when viewed from
    /calendar/, silently failing to refresh the visible page."""
    client, user = logged_in_client
    task = Task.objects.create(user=user, title="Finish me", status="todo")

    response = client.post(
        reverse("boards:task-move", args=[task.pk]),
        {"new_status": "done"},
        HTTP_HX_TARGET="task-list-content",
        HTTP_HX_CURRENT_URL=_calendar_current_url(),
    )
    task.refresh_from_db()
    content = response.content.decode()

    assert response.status_code == 200
    assert task.completed_at is not None
    assert "calendar-month-grid" in content
    assert "board-column" not in content


@pytest.mark.django_db
def test_board_filter_from_calendar_page_rerenders_calendar_body(logged_in_client):
    client, user = logged_in_client
    board = Board.objects.get(user=user)

    response = client.post(
        reverse("boards:board-filter"),
        {"board_id": board.pk, "tags": "urgent"},
        HTTP_HX_CURRENT_URL=_calendar_current_url(),
    )
    content = response.content.decode()
    assert response.status_code == 200
    assert "calendar-month-grid" in content


@pytest.mark.django_db
def test_saved_filter_load_from_calendar_page_rerenders_calendar_body(logged_in_client):
    from apps.boards.models import SavedFilter

    client, user = logged_in_client
    board = Board.objects.get(user=user)
    saved = SavedFilter.objects.create(board=board, name="Urgent", filter_config={"tags": ["urgent"]})

    response = client.post(
        reverse("boards:filter-load", args=[saved.pk]),
        {},
        HTTP_HX_CURRENT_URL=_calendar_current_url(),
    )
    content = response.content.decode()
    assert response.status_code == 200
    assert "calendar-month-grid" in content


# ---------------------------------------------------------------------------
# Task panel: due_date pre-fill, origin-aware responses
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_task_panel_create_get_honors_due_date_param(logged_in_client):
    client, _ = logged_in_client
    response = client.get(reverse("boards:task-panel-create"), {"due_date": "2026-09-20"})
    assert response.status_code == 200
    assert 'value="2026-09-20"' in response.content.decode()


@pytest.mark.django_db
def test_task_panel_create_post_from_calendar_returns_calendar_oob(logged_in_client):
    client, _ = logged_in_client
    response = client.post(
        reverse("boards:task-panel-create"),
        {"title": "Quick add", "team": "", "due_date": "", "tags": "",
         "recurrence_days": "", "recurrence_from": "completion"},
        HTTP_HX_CURRENT_URL=_calendar_current_url(),
    )
    content = response.content.decode()
    assert response.status_code == 200
    assert "calendar-month-grid" in content
    assert "board-column" not in content


@pytest.mark.django_db
def test_task_panel_create_post_from_board_returns_board_oob(logged_in_client):
    client, _ = logged_in_client
    response = client.post(
        reverse("boards:task-panel-create"),
        {"title": "Quick add", "team": "", "due_date": "", "tags": "",
         "recurrence_days": "", "recurrence_from": "completion"},
        HTTP_HX_CURRENT_URL="http://testserver/board/",
    )
    content = response.content.decode()
    assert response.status_code == 200
    assert "board-column" in content
    assert "calendar-month-grid" not in content


@pytest.mark.django_db
def test_task_panel_update_from_calendar_oob_uses_compact_card(logged_in_client):
    client, user = logged_in_client
    task = Task.objects.create(user=user, title="Editable", status="todo")

    response = client.post(
        reverse("boards:task-panel-update", args=[task.pk]),
        {"title": "Editable", "notes": "", "due_date": "", "tags": "",
         "recurrence_days": "", "recurrence_from": "completion"},
        HTTP_HX_CURRENT_URL=_calendar_current_url(),
    )
    content = response.content.decode()
    assert response.status_code == 200
    assert "task-card--compact" in content


@pytest.mark.django_db
def test_task_panel_update_from_board_oob_uses_full_card(logged_in_client):
    client, user = logged_in_client
    task = Task.objects.create(user=user, title="Editable", status="todo")

    response = client.post(
        reverse("boards:task-panel-update", args=[task.pk]),
        {"title": "Editable", "notes": "", "due_date": "", "tags": "",
         "recurrence_days": "", "recurrence_from": "completion"},
        HTTP_HX_CURRENT_URL="http://testserver/board/",
    )
    content = response.content.decode()
    assert response.status_code == 200
    assert "task-card--compact" not in content


# ---------------------------------------------------------------------------
# Nav
# ---------------------------------------------------------------------------


def _calendar_nav_link_html(content):
    match = re.search(r'<a class="nav-link[^"]*" href="/calendar/">Calendar</a>', content)
    assert match, "calendar nav link not found"
    return match.group(0)


@pytest.mark.django_db
def test_calendar_nav_link_active_on_calendar_page(logged_in_client):
    client, _ = logged_in_client
    response = client.get(reverse("calendar:calendar"))
    assert "is-active" in _calendar_nav_link_html(response.content.decode())


@pytest.mark.django_db
def test_calendar_nav_link_inactive_on_board_page(logged_in_client):
    client, _ = logged_in_client
    response = client.get(reverse("boards:board"))
    assert "is-active" not in _calendar_nav_link_html(response.content.decode())
