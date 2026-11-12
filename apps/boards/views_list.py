"""The list view: every task on the board in one list, sorted and grouped.

It reads the same filter as the board and calendar (apps/boards/filtering.py)
plus the list-only parts: sort, grouping, collapsed groups and "show done".
"""

from urllib.parse import urlparse

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps.tasks.selectors import board_tasks_qs

from .filtering import LIST_IGNORES, SORT_DESC, board_filter_for, save_board_filter
from .listing import group_tasks, sort_tasks
from .selectors import resolve_board
from .views import _board_from_post, _status_context_for, filter_bar_context

SORT_OPTIONS = (
    ("manual", "Board order"),
    ("due", "Due date"),
    ("status", "Status"),
    ("assignee", "Assignee"),
    ("title", "Title"),
    ("created", "Created"),
    ("updated", "Updated"),
)
GROUP_OPTIONS = (
    ("none", "Nothing"),
    ("status", "Status"),
    ("assignee", "Assignee"),
    ("due", "Due date"),
    ("tag", "Tag"),
)


def is_list_page(request):
    """Whether the htmx request came from the list page. Mutations shared with
    the board and calendar (move, delete, panel saves) answer each page with
    its own markup, the same way the calendar is told apart."""
    path = urlparse(request.headers.get("HX-Current-URL", "")).path
    return path == reverse("boards:list")


def build_list_context(user, board, session=None):
    today = timezone.localdate()
    task_filter = board_filter_for(board, session)

    all_tasks = list(board_tasks_qs(board).filter(is_archived=False))
    tasks = task_filter.apply(all_tasks, today)
    if not task_filter.show_done:
        tasks = [t for t in tasks if not t.completed_at]

    statuses, done_slug, active_slug = _status_context_for(user)
    status_by_slug = {status.slug: status for status in statuses}
    for task in tasks:
        task.done_slug, task.active_slug = done_slug, active_slug
        task.status_obj = status_by_slug.get(task.status)

    ordered = sort_tasks(tasks, task_filter.sort, task_filter.sort_dir, statuses)
    groups = group_tasks(ordered, task_filter.group, statuses=statuses, viewer=user, today=today)
    for number, group in enumerate(groups):
        group["collapsed"] = group["key"] in task_filter.collapsed_groups
        group["dom_id"] = f"list-group-{number}"

    return {
        "board": board,
        "groups": groups,
        "grouped": task_filter.group != "none",
        "statuses": statuses,
        "done_slug": done_slug,
        "active_slug": active_slug,
        "today": today,
        "list_view": True,
        "show_task_search": True,
        "layout": {
            "sort": task_filter.sort,
            "sort_desc": task_filter.sort_dir == SORT_DESC,
            "group": task_filter.group,
            "show_done": task_filter.show_done,
        },
        "sort_options": SORT_OPTIONS,
        "group_options": GROUP_OPTIONS,
        "total_task_count": len(all_tasks),
        "visible_task_count": len(tasks),
        "hidden_task_count": len(all_tasks) - len(tasks),
        "done_task_count": sum(1 for task in all_tasks if task.completed_at),
        **filter_bar_context(task_filter, [], list(board.saved_filters.all()), LIST_IGNORES),
    }


def render_list_body(request, board):
    """The list and the filter bar, for a filter or layout change."""
    context = build_list_context(request.user, board, request.session)
    return render(request, "boards/list/_filter_response.html", context)


class ListView(LoginRequiredMixin, View):
    def get(self, request):
        board = resolve_board(request.user)
        context = build_list_context(request.user, board, request.session)
        return render(request, "boards/list/list.html", context)


class ListLayoutView(LoginRequiredMixin, View):
    """Change how the list is sorted or grouped."""

    def post(self, request):
        board = _board_from_post(request)
        task_filter = board_filter_for(board, request.session)
        save_board_filter(request, board, task_filter.with_layout_from(request.POST))
        return render_list_body(request, board)


class ListGroupToggleView(LoginRequiredMixin, View):
    """Collapse or expand one group of the list."""

    def post(self, request):
        board = _board_from_post(request)
        key = request.POST.get("key", "")
        if ":" not in key or len(key) > 300:
            raise Http404()
        task_filter = board_filter_for(board, request.session)
        save_board_filter(request, board, task_filter.toggling_group(key))
        return render_list_body(request, board)
