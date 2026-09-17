import calendar as calendar_module
from datetime import date

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from apps.tasks.selectors import board_tasks_qs, get_task_or_404, reschedule_task

from .selectors import resolve_board
from .views import (
    _board_filter_for,
    _hidden_lane_context,
    _matching_saved_filter_name,
    _status_context_for,
    _task_matches_assignee,
)

DAY_OVERFLOW_THRESHOLD = 3


def _shift_month(year, month, delta):
    """(year, month) delta months away, wrapping across year boundaries."""
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


def _normalize_year_month(year_param, month_param):
    today = timezone.localdate()
    try:
        year = int(year_param)
        month = int(month_param)
        if not (1 <= month <= 12):
            raise ValueError
    except (TypeError, ValueError):
        return today.year, today.month
    return year, month


def _build_calendar_context(user, board, year, month, session=None):
    today = timezone.localdate()

    board_filter = _board_filter_for(board, session)
    filter_tags = board_filter.get("tags", [])
    exclude_tags = board_filter.get("exclude_tags", [])
    filter_assignee = board_filter.get("assignee", "").strip()
    hidden_lane_keys = set(board_filter.get("hidden_lanes", []))
    hidden_lane_matchers, hidden_lane_summaries = _hidden_lane_context(user, board, hidden_lane_keys)
    # board's "due" session filter is deliberately never read here -- month
    # navigation is the calendar's equivalent of that filter.

    cal = calendar_module.Calendar(firstweekday=6)  # Sunday-start weeks
    weeks = cal.monthdatescalendar(year, month)
    grid_start, grid_end = weeks[0][0], weeks[-1][-1]

    all_tasks = list(board_tasks_qs(board).filter(is_archived=False))

    if filter_tags:
        all_tasks = [t for t in all_tasks if all(tag in t.tags for tag in filter_tags)]
    if exclude_tags:
        all_tasks = [t for t in all_tasks if not any(tag in t.tags for tag in exclude_tags)]
    if filter_assignee:
        all_tasks = [t for t in all_tasks if _task_matches_assignee(t, filter_assignee, user)]
    if hidden_lane_matchers:
        all_tasks = [t for t in all_tasks if not any(matches(t) for matches in hidden_lane_matchers)]

    dated = [t for t in all_tasks if t.due_date and grid_start <= t.due_date <= grid_end]
    undated = [t for t in all_tasks if not t.due_date]

    statuses, done_slug, active_slug = _status_context_for(user, board.team)

    by_date = {}
    for t in dated:
        t.done_slug, t.active_slug = done_slug, active_slug
        by_date.setdefault(t.due_date, []).append(t)

    def _sort_key(t):
        # date-only ("all-day") tasks first, then chronological by due_time
        if t.due_time is None:
            return (0, "", t.title)
        return (1, t.due_time, t.title)

    weeks_ctx = []
    for week in weeks:
        cells = []
        for day in week:
            day_tasks = sorted(by_date.get(day, []), key=_sort_key)
            cells.append({
                "date": day,
                "in_month": day.month == month,
                "is_today": day == today,
                "tasks": day_tasks[:DAY_OVERFLOW_THRESHOLD],
                "overflow_tasks": day_tasks[DAY_OVERFLOW_THRESHOLD:],
                "overflow_count": max(0, len(day_tasks) - DAY_OVERFLOW_THRESHOLD),
            })
        weeks_ctx.append(cells)

    undated_sorted = sorted(undated, key=lambda t: (t.order, t.created_at))
    for t in undated_sorted:
        t.done_slug, t.active_slug = done_slug, active_slug

    prev_year, prev_month = _shift_month(year, month, -1)
    next_year, next_month = _shift_month(year, month, 1)

    active_filter = {
        "tags": filter_tags,
        "exclude_tags": exclude_tags,
        "due": "",
        "assignee": filter_assignee,
        "hidden_lanes": hidden_lane_summaries,
    }
    saved_filters = list(board.saved_filters.all())

    return {
        "board": board,
        "year": year,
        "month": month,
        "month_label": date(year, month, 1).strftime("%B %Y"),
        "weeks": weeks_ctx,
        "undated_tasks": undated_sorted,
        "statuses": statuses,
        "done_slug": done_slug,
        "active_slug": active_slug,
        "today": today,
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "today_year": today.year,
        "today_month": today.month,
        "active_filter": active_filter,
        "active_filter_count": (
            len(filter_tags) + len(exclude_tags) + len(hidden_lane_keys) + (1 if filter_assignee else 0)
        ),
        "saved_filters": saved_filters,
        "active_saved_filter_name": _matching_saved_filter_name(
            saved_filters, filter_tags, exclude_tags, "", filter_assignee, hidden_lane_keys
        ),
        "hide_due_filter": True,
        "team_members": list(board.team.memberships.select_related("user")) if board.team_id else [],
    }


class CalendarView(LoginRequiredMixin, View):
    def get(self, request, team_id=None):
        from apps.tasks.selectors import user_teams_qs

        board = resolve_board(request.user, team_id)
        year, month = _normalize_year_month(request.GET.get("year"), request.GET.get("month"))
        context = _build_calendar_context(request.user, board, year, month, request.session)
        context["user_teams"] = list(user_teams_qs(request.user))
        return render(request, "calendar/calendar.html", context)


class TaskRescheduleView(LoginRequiredMixin, View):
    def post(self, request, pk):
        from .views import _board_for_task, _calendar_params_from_request

        task = get_task_or_404(request.user, pk)
        raw = request.POST.get("due_date", "").strip()
        new_due_date = None
        if raw:
            try:
                new_due_date = date.fromisoformat(raw)
            except ValueError:
                return HttpResponse(status=422)

        reschedule_task(request.user, task, new_due_date)

        board = _board_for_task(task)
        # The drag-and-drop POST carries no ?year=&month= of its own -- read the
        # month the calendar page currently has open from HX-Current-URL (the same
        # mechanism the board/calendar page-detection helpers use), so a reschedule
        # doesn't snap the view back to today's month.
        _, year, month = _calendar_params_from_request(request)
        if year is None:
            ref = new_due_date or timezone.localdate()
            year, month = ref.year, ref.month
        context = _build_calendar_context(request.user, board, year, month, request.session)
        return render(request, "calendar/_calendar_body.html", context)
