import json
import re
import markdown as md
from datetime import date, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views import View

from apps.tasks.models import Task, TaskComment, TaskStatus
from apps.tasks.selectors import (
    AssignmentError,
    InvalidStatusError,
    assign_task,
    board_tasks_qs,
    get_task_or_404,
    move_task,
    user_teams_qs,
    visible_statuses_qs,
    visible_tasks_qs,
)
from apps.users.models import User

from .models import Board, Column, SavedFilter
from .selectors import resolve_board, user_can_access_board

TASK_CHECKBOX_PATTERN = re.compile(r"<(?P<tag>li|p)>\[(?P<state>[xX ])\]\s*(?P<body>.*?)</(?P=tag)>", re.DOTALL)


def _board_for_team(user, team):
    """The personal board (team is None) or a team's shared board -- team membership
    is assumed already validated by the caller (e.g. via _resolve_team_param)."""
    return Board.objects.get(team=team) if team else Board.objects.get(user=user)


def _board_for_task(task):
    """The board a task belongs on: its team's shared board, or its owner's personal board."""
    return Board.objects.get(team_id=task.team_id) if task.team_id else Board.objects.get(user_id=task.user_id)


def _board_from_post(request):
    """Resolve+authorize a board named by a hidden 'board_id' field, for actions with no
    other pk (column/saved-filter/task) to derive the board from."""
    board_id = request.POST.get("board_id", "")
    if not board_id.isdigit():
        raise Http404()
    board = get_object_or_404(Board, pk=int(board_id))
    if not user_can_access_board(request.user, board):
        raise Http404()
    return board


def _task_matches_assignee(task, assignee_filter, user):
    if not assignee_filter or assignee_filter == "any":
        return True
    if assignee_filter == "me":
        return task.assignee_id == user.id
    if assignee_filter == "unassigned":
        return task.assignee_id is None
    return str(task.assignee_id) == str(assignee_filter)


def _task_matches_column(task, filter_config, user):
    statuses = filter_config.get("statuses", [])
    tags = filter_config.get("tags", [])
    due = filter_config.get("due")

    if not _task_matches_assignee(task, filter_config.get("assignee"), user):
        return False
    if statuses and task.status not in statuses:
        return False
    if tags and not any(t in task.tags for t in tags):
        return False
    if due == "overdue":
        today = date.today()
        if not task.due_date or task.due_date >= today:
            return False
    elif due == "today":
        if task.due_date != date.today():
            return False
    elif due == "this_week":
        today = date.today()
        end = today + timedelta(days=7)
        if not task.due_date or task.due_date < today or task.due_date > end:
            return False
    return True


def _status_context_for(user, team=None):
    statuses = list(visible_statuses_qs(user, team=team))
    done_slug = next((s.slug for s in statuses if s.is_done), "done")
    active_slug = next((s.slug for s in statuses if not s.is_done), "todo")
    return statuses, done_slug, active_slug


def _status_context(user):
    return _status_context_for(user, team=None)


def _resolve_team_param(user, team_id_str):
    """Returns None (personal), a Team the user belongs to, or False (invalid/not a member)."""
    if not team_id_str:
        return None
    if not team_id_str.isdigit():
        return False
    team = user_teams_qs(user).filter(pk=int(team_id_str)).first()
    return team if team else False


def _resolve_status_slug(status, statuses):
    valid_slugs = [item.slug for item in statuses]
    if status in valid_slugs:
        return status
    return valid_slugs[0] if valid_slugs else "todo"


def _column_for_status(columns, status_slug):
    """Finds the lane that would display a task carrying this status, for labeling purposes."""
    for column in columns:
        if status_slug in column.filter_config.get("statuses", []):
            return column
    for column in columns:
        if not column.filter_config.get("statuses", []):
            return column
    return columns[0] if columns else None


def _resolve_task_create_selection(user, board, statuses, requested_column_id=""):
    """Returns (column_or_None, status_slug) for a new task via the create panel."""
    columns = list(board.columns.all())

    if str(requested_column_id).isdigit():
        requested_pk = int(requested_column_id)
        for column in columns:
            if column.pk == requested_pk:
                return column, column.default_status(user, team=board.team)

    if board.team_id is None and user.default_status_id:
        status_slug = _resolve_status_slug(user.default_status.slug, statuses)
        return _column_for_status(columns, status_slug), status_slug

    if columns:
        column = columns[0]
        return column, column.default_status(user, team=board.team)

    return None, _resolve_status_slug("", statuses)


def _task_render_context(user, task):
    statuses, done_slug, active_slug = _status_context_for(user, task.team)
    return {
        "task": task,
        "board": _board_for_task(task),
        "statuses": statuses,
        "done_slug": done_slug,
        "active_slug": active_slug,
        "today": timezone.localdate(),
    }


def _task_panel_context(user, task):
    context = _task_render_context(user, task)
    context.update({
        "notes_html": _render_markdown(task.notes) if task.notes else "",
        "comments": _render_comments(task),
        "activity": task.activity.all() if task.team_id else [],
        "team_members": list(task.team.memberships.select_related("user")) if task.team_id else [],
    })
    return context


def _task_panel_create_context(user, board, column_id="", form_values=None, form_error=""):
    team = board.team
    statuses, done_slug, active_slug = _status_context_for(user, team)
    selected_column, selected_status = _resolve_task_create_selection(user, board, statuses, column_id)
    selected_status_name = next((item.name for item in statuses if item.slug == selected_status), selected_status)
    form_values = form_values or {}

    return {
        "statuses": statuses,
        "done_slug": done_slug,
        "active_slug": active_slug,
        "today": timezone.localdate(),
        "selected_column": selected_column,
        "selected_column_id": selected_column.pk if selected_column else "",
        "selected_column_name": selected_column.label if selected_column else "your board",
        "selected_status": selected_status,
        "selected_status_name": selected_status_name,
        "selected_team": team,
        "selected_team_id": team.pk if team else "",
        "title_value": form_values.get("title", ""),
        "notes_value": form_values.get("notes", ""),
        "due_date_value": form_values.get("due_date", ""),
        "tags_value": form_values.get("tags", ""),
        "recurrence_days_value": form_values.get("recurrence_days", ""),
        "recurrence_from_value": form_values.get("recurrence_from", Task.RECURRENCE_FROM_COMPLETION),
        "form_error": form_error,
    }


def _board_filter_for(board, session):
    """This board's slice of the session's per-board tag/due/hidden-column filters."""
    all_filters = (session.get("board_filter") or {}) if session else {}
    return all_filters.get(str(board.pk), {})


def _set_board_filter(request, board, board_filter):
    all_filters = request.session.get("board_filter") or {}
    all_filters[str(board.pk)] = board_filter
    request.session["board_filter"] = all_filters
    request.session.modified = True


def _build_board_context(user, board, session=None):
    columns = list(board.columns.all())
    today = timezone.localdate()

    board_filter = _board_filter_for(board, session)
    filter_tags = board_filter.get("tags", [])
    exclude_tags = board_filter.get("exclude_tags", [])
    filter_due = board_filter.get("due", "").strip()
    hidden_column_pks = set(board_filter.get("hidden_columns", []))

    all_tasks = list(board_tasks_qs(board).filter(is_archived=False).order_by("order", "created_at"))
    tasks = list(all_tasks)

    if filter_tags:
        tasks = [t for t in tasks if all(tag in t.tags for tag in filter_tags)]
    if exclude_tags:
        tasks = [t for t in tasks if not any(tag in t.tags for tag in exclude_tags)]
    if filter_due:
        if filter_due == "overdue":
            tasks = [t for t in tasks if t.due_date and t.due_date < today]
        elif filter_due == "today":
            tasks = [t for t in tasks if t.due_date == today]
        elif filter_due == "this_week":
            end = today + timedelta(days=7)
            tasks = [t for t in tasks if t.due_date and today <= t.due_date <= end]

    statuses, done_slug, active_slug = _status_context_for(user, board.team)

    hidden_columns = []
    claimed = set()
    columns_with_tasks = []
    for column in columns:
        if column.pk in hidden_column_pks:
            hidden_columns.append(column)
            continue
        col_tasks = []
        for task in tasks:
            if task.pk not in claimed and _task_matches_column(task, column.filter_config, user):
                task.done_slug, task.active_slug = done_slug, active_slug
                col_tasks.append(task)
                claimed.add(task.pk)
        columns_with_tasks.append((column, col_tasks, column.default_status(user, team=board.team)))

    saved_filters = list(board.saved_filters.all())
    active_saved_filter_name = None
    current_config = {
        "tags": filter_tags,
        "exclude_tags": exclude_tags,
        "due": filter_due,
        "hidden_columns": list(hidden_column_pks),
    }
    for sf in saved_filters:
        sf_config = sf.filter_config
        if (
            sorted(sf_config.get("tags", [])) == sorted(current_config["tags"])
            and sorted(sf_config.get("exclude_tags", [])) == sorted(current_config["exclude_tags"])
            and sf_config.get("due", "") == current_config["due"]
            and sorted(sf_config.get("hidden_columns", [])) == sorted(current_config["hidden_columns"])
        ):
            active_saved_filter_name = sf.name
            break

    return {
        "board": board,
        "columns_with_tasks": columns_with_tasks,
        "statuses": statuses,
        "done_slug": done_slug,
        "active_slug": active_slug,
        "active_filter": {
            "tags": filter_tags,
            "exclude_tags": exclude_tags,
            "due": filter_due,
            "hidden_columns": hidden_columns,
        },
        "saved_filters": saved_filters,
        "active_saved_filter_name": active_saved_filter_name,
        "today": today,
        "total_task_count": len(all_tasks),
        "visible_task_count": len(tasks),
        "done_task_count": sum(1 for task in all_tasks if task.completed_at),
        "due_today_count": sum(1 for task in tasks if task.due_date == today and not task.completed_at),
        "overdue_count": sum(1 for task in tasks if task.due_date and task.due_date < today and not task.completed_at),
        "active_filter_count": len(filter_tags) + len(exclude_tags) + len(hidden_column_pks) + (1 if filter_due else 0),
    }


class BoardView(LoginRequiredMixin, View):
    def get(self, request, team_id=None):
        board = resolve_board(request.user, team_id)
        context = _build_board_context(request.user, board, request.session)
        context["user_teams"] = list(user_teams_qs(request.user))
        return render(request, "boards/board.html", context)


class BoardFilterView(LoginRequiredMixin, View):
    def post(self, request):
        board = _board_from_post(request)
        tags = request.POST.getlist("tags")
        exclude_tags = request.POST.getlist("exclude_tags")
        due = request.POST.get("due", "").strip()
        hidden_columns = [int(pk) for pk in request.POST.getlist("hidden_columns") if pk.isdigit()]
        _set_board_filter(request, board, {
            "tags": tags,
            "exclude_tags": exclude_tags,
            "due": due,
            "hidden_columns": hidden_columns,
        })
        context = _build_board_context(request.user, board, request.session)
        return render(request, "boards/_filter_response.html", context)


class BoardFilterAddTagView(LoginRequiredMixin, View):
    """Add a single tag to the active (inclusive) filter without replacing existing ones."""

    def post(self, request):
        board = _board_from_post(request)
        tag = request.POST.get("tag", "").strip()
        board_filter = _board_filter_for(board, request.session)
        current_tags = board_filter.get("tags", [])
        exclude_tags = [t for t in board_filter.get("exclude_tags", []) if t != tag]
        due = board_filter.get("due", "")
        hidden_columns = board_filter.get("hidden_columns", [])
        if tag and tag not in current_tags:
            current_tags = current_tags + [tag]
        _set_board_filter(request, board, {
            "tags": current_tags,
            "exclude_tags": exclude_tags,
            "due": due,
            "hidden_columns": hidden_columns,
        })
        context = _build_board_context(request.user, board, request.session)
        return render(request, "boards/_filter_response.html", context)


class BoardFilterExcludeTagView(LoginRequiredMixin, View):
    """Add a single tag to the active exclude filter without replacing existing ones."""

    def post(self, request):
        board = _board_from_post(request)
        tag = request.POST.get("tag", "").strip()
        board_filter = _board_filter_for(board, request.session)
        current_tags = [t for t in board_filter.get("tags", []) if t != tag]
        exclude_tags = board_filter.get("exclude_tags", [])
        due = board_filter.get("due", "")
        hidden_columns = board_filter.get("hidden_columns", [])
        if tag and tag not in exclude_tags:
            exclude_tags = exclude_tags + [tag]
        _set_board_filter(request, board, {
            "tags": current_tags,
            "exclude_tags": exclude_tags,
            "due": due,
            "hidden_columns": hidden_columns,
        })
        context = _build_board_context(request.user, board, request.session)
        return render(request, "boards/_filter_response.html", context)


class ColumnHideView(LoginRequiredMixin, View):
    """Add a column to the session hidden-columns filter."""

    def post(self, request, pk):
        column = get_object_or_404(Column.objects.select_related("board"), pk=pk)
        if not user_can_access_board(request.user, column.board):
            raise Http404()
        board = column.board
        board_filter = _board_filter_for(board, request.session)
        hidden = board_filter.get("hidden_columns", [])
        if column.pk not in hidden:
            hidden = hidden + [column.pk]
        _set_board_filter(request, board, {**board_filter, "hidden_columns": hidden})
        context = _build_board_context(request.user, board, request.session)
        return render(request, "boards/_filter_response.html", context)


class ColumnReorderView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            order = data.get("order", [])
        except (json.JSONDecodeError, AttributeError):
            return HttpResponse(status=400)

        columns = {c.pk: c for c in Column.objects.filter(pk__in=order).select_related("board")}
        if columns:
            board = next(iter(columns.values())).board
            if not user_can_access_board(request.user, board) or any(
                c.board_id != board.pk for c in columns.values()
            ):
                return HttpResponse(status=403)

        for i, pk in enumerate(order):
            if pk in columns:
                columns[pk].order = i
                columns[pk].save(update_fields=["order"])

        return HttpResponse(status=204)


class TaskReorderView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            order = data.get("order", [])
        except (json.JSONDecodeError, AttributeError):
            return HttpResponse(status=400)

        tasks = {t.pk: t for t in visible_tasks_qs(request.user).filter(pk__in=order)}
        for i, pk in enumerate(order):
            if pk in tasks:
                tasks[pk].order = i
                tasks[pk].save(update_fields=["order"])

        return HttpResponse(status=204)


class TaskCreateView(LoginRequiredMixin, View):
    def post(self, request):
        team = _resolve_team_param(request.user, request.POST.get("team", "").strip())
        if team is False:
            return HttpResponse(status=422)

        statuses, _, _ = _status_context_for(request.user, team)
        status = _resolve_status_slug(request.POST.get("status", "").strip(), statuses)
        title = request.POST.get("title", "").strip()

        if not title:
            return HttpResponse(status=422)

        task = Task.objects.create(user=request.user, team=team, title=title, status=status)
        return render(request, "partials/task_card.html", _task_render_context(request.user, task))


class TaskUpdateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        task = get_task_or_404(request.user, pk)
        title = request.POST.get("title", "").strip()
        notes = request.POST.get("notes", "")
        due_date = request.POST.get("due_date") or None

        tags_raw = request.POST.get("tags", "")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

        recurrence_days_raw = request.POST.get("recurrence_days", "").strip()
        recurrence_days = int(recurrence_days_raw) if recurrence_days_raw.isdigit() else None
        recurrence_from = request.POST.get("recurrence_from", Task.RECURRENCE_FROM_COMPLETION)
        if recurrence_from not in (Task.RECURRENCE_FROM_COMPLETION, Task.RECURRENCE_FROM_DUE_DATE):
            recurrence_from = Task.RECURRENCE_FROM_COMPLETION

        if title:
            task.title = title
        task.notes = notes
        task.due_date = due_date
        task.tags = tags
        task.recurrence_days = recurrence_days
        task.recurrence_from = recurrence_from
        task.save(update_fields=["title", "notes", "due_date", "tags", "recurrence_days", "recurrence_from", "updated_at"])

        return render(request, "partials/task_card.html", _task_render_context(request.user, task))


class TaskMoveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        task = get_task_or_404(request.user, pk)
        new_status = request.POST.get("new_status", "")

        try:
            move_task(request.user, task, new_status)
        except InvalidStatusError:
            return HttpResponse(status=422)

        board = _board_for_task(task)
        if request.headers.get("HX-Target") == "task-panel-content":
            context = _task_panel_context(request.user, task)
            context.update(_build_board_context(request.user, board, request.session))
            return render(request, "partials/task_panel_board_response.html", context)

        context = _build_board_context(request.user, board, request.session)
        return render(request, "boards/_columns.html", context)


class TaskAssignView(LoginRequiredMixin, View):
    def post(self, request, pk):
        task = get_task_or_404(request.user, pk)
        assignee_id = request.POST.get("assignee_id", "").strip()
        assignee = get_object_or_404(User, pk=assignee_id) if assignee_id else None

        try:
            assign_task(request.user, task, assignee)
        except AssignmentError:
            return HttpResponse(status=422)

        if request.headers.get("HX-Target") == "task-panel-content":
            context = _task_panel_context(request.user, task)
            return render(request, "partials/task_panel_content.html", context)

        return render(request, "partials/task_card.html", _task_render_context(request.user, task))


class TaskDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        task = get_task_or_404(request.user, pk)
        task.delete()
        return HttpResponse("")


class ColumnArchiveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        column = get_object_or_404(Column.objects.select_related("board"), pk=pk)
        if not user_can_access_board(request.user, column.board):
            raise Http404()
        board = column.board

        # Mirror the claimed-task logic from _build_board_context to find exactly
        # which tasks are visible in this column.
        all_tasks = list(board_tasks_qs(board).filter(is_archived=False).order_by("order", "created_at"))
        claimed = set()
        to_archive = []
        for col in board.columns.all():
            for task in all_tasks:
                if task.pk not in claimed and _task_matches_column(task, col.filter_config, request.user):
                    if col.pk == column.pk:
                        to_archive.append(task.pk)
                    claimed.add(task.pk)

        Task.objects.filter(pk__in=to_archive).update(is_archived=True)

        context = _build_board_context(request.user, board, request.session)
        return render(request, "boards/_columns.html", context)


class TaskDetailView(LoginRequiredMixin, View):
    """Return the read-only task card partial. Used by the edit form's Cancel button."""

    def get(self, request, pk):
        task = get_task_or_404(request.user, pk)
        return render(request, "partials/task_card.html", _task_render_context(request.user, task))


class TaskEditView(LoginRequiredMixin, View):
    """Return the edit form partial. Triggered by clicking the task title."""

    def get(self, request, pk):
        task = get_task_or_404(request.user, pk)
        return render(request, "partials/task_edit_form.html", {"task": task})


class TaskPanelView(LoginRequiredMixin, View):
    """Return the panel read-mode content."""

    def get(self, request, pk):
        task = get_task_or_404(request.user, pk)
        context = _task_panel_context(request.user, task)
        return render(request, "partials/task_panel_content.html", context)


class TaskPanelCreateView(LoginRequiredMixin, View):
    """Return the panel create-mode content and handle initial task creation."""

    def get(self, request):
        team = _resolve_team_param(request.user, request.GET.get("team", "").strip())
        if team is False:
            team = None
        board = _board_for_team(request.user, team)
        context = _task_panel_create_context(request.user, board, request.GET.get("column", "").strip())
        return render(request, "partials/task_panel_create.html", context)

    def post(self, request):
        team = _resolve_team_param(request.user, request.POST.get("team", "").strip())
        if team is False:
            return HttpResponse(status=422)
        board = _board_for_team(request.user, team)

        form_values = {
            "title": request.POST.get("title", "").strip(),
            "notes": request.POST.get("notes", ""),
            "due_date": request.POST.get("due_date", ""),
            "tags": request.POST.get("tags", ""),
            "recurrence_days": request.POST.get("recurrence_days", "").strip(),
            "recurrence_from": request.POST.get("recurrence_from", Task.RECURRENCE_FROM_COMPLETION),
        }
        context = _task_panel_create_context(
            request.user,
            board,
            request.POST.get("column", "").strip(),
            form_values=form_values,
        )

        if not form_values["title"]:
            context["form_error"] = "Add a title before creating the task."
            return render(request, "partials/task_panel_create.html", context, status=422)

        tags = [tag.strip() for tag in form_values["tags"].split(",") if tag.strip()]
        recurrence_days = int(form_values["recurrence_days"]) if form_values["recurrence_days"].isdigit() else None
        recurrence_from = form_values["recurrence_from"]
        if recurrence_from not in (Task.RECURRENCE_FROM_COMPLETION, Task.RECURRENCE_FROM_DUE_DATE):
            recurrence_from = Task.RECURRENCE_FROM_COMPLETION

        task = Task.objects.create(
            user=request.user,
            team=team,
            title=form_values["title"],
            notes=form_values["notes"],
            status=context["selected_status"],
            due_date=form_values["due_date"] or None,
            tags=tags,
            recurrence_days=recurrence_days,
            recurrence_from=recurrence_from,
        )

        panel_context = _task_panel_context(request.user, task)
        panel_context.update(_build_board_context(request.user, board, request.session))
        return render(request, "partials/task_panel_board_response.html", panel_context)


class TaskPanelEditView(LoginRequiredMixin, View):
    """Return the panel edit-mode content."""

    def get(self, request, pk):
        task = get_task_or_404(request.user, pk)
        context = _task_render_context(request.user, task)
        return render(request, "partials/task_panel_edit.html", context)


class TaskPanelUpdateView(LoginRequiredMixin, View):
    """Save task from the panel; returns updated panel read-mode + OOB card update."""

    def post(self, request, pk):
        task = get_task_or_404(request.user, pk)
        title = request.POST.get("title", "").strip()
        notes = request.POST.get("notes", "")
        due_date = request.POST.get("due_date") or None
        tags_raw = request.POST.get("tags", "")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

        recurrence_days_raw = request.POST.get("recurrence_days", "").strip()
        recurrence_days = int(recurrence_days_raw) if recurrence_days_raw.isdigit() else None
        recurrence_from = request.POST.get("recurrence_from", Task.RECURRENCE_FROM_COMPLETION)
        if recurrence_from not in (Task.RECURRENCE_FROM_COMPLETION, Task.RECURRENCE_FROM_DUE_DATE):
            recurrence_from = Task.RECURRENCE_FROM_COMPLETION

        if title:
            task.title = title
        task.notes = notes
        task.due_date = due_date
        task.tags = tags
        task.recurrence_days = recurrence_days
        task.recurrence_from = recurrence_from
        task.save(update_fields=["title", "notes", "due_date", "tags", "recurrence_days", "recurrence_from", "updated_at"])

        context = _task_panel_context(request.user, task)
        return render(request, "partials/task_panel_update_response.html", context)


def _replace_task_checkbox(match):
    tag = match.group("tag")
    body = match.group("body").strip()
    checked = match.group("state").lower() == "x"
    state_class = " rendered-checkbox-line--checked" if checked else ""
    return (
        f'<{tag} class="rendered-checkbox-line{state_class}">'
        '<span class="rendered-checkbox" aria-hidden="true"></span>'
        f'<span class="rendered-checkbox-label">{body}</span>'
        f"</{tag}>"
    )


def _render_markdown(text):
    html = md.markdown(text, extensions=["fenced_code", "tables"])
    return TASK_CHECKBOX_PATTERN.sub(_replace_task_checkbox, html)


def _render_comments(task):
    return [
        {"comment": c, "body_html": _render_markdown(c.body)}
        for c in task.comments.all()
    ]


class TaskCommentCreateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        task = get_task_or_404(request.user, pk)
        body = request.POST.get("body", "").strip()
        if body:
            TaskComment.objects.create(task=task, body=body)
        return render(request, "partials/task_comments.html", {
            "task": task,
            "comments": _render_comments(task),
        })


class TaskCommentDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk, comment_pk):
        task = get_task_or_404(request.user, pk)
        comment = get_object_or_404(TaskComment, pk=comment_pk, task=task)
        comment.delete()
        return render(request, "partials/task_comments.html", {
            "task": task,
            "comments": _render_comments(task),
        })


class SavedFilterLoadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        saved_filter = get_object_or_404(SavedFilter.objects.select_related("board"), pk=pk)
        if not user_can_access_board(request.user, saved_filter.board):
            raise Http404()
        board = saved_filter.board
        _set_board_filter(request, board, saved_filter.filter_config)
        context = _build_board_context(request.user, board, request.session)
        return render(request, "boards/_filter_response.html", context)


class SavedFilterSaveView(LoginRequiredMixin, View):
    def post(self, request):
        board = _board_from_post(request)
        name = request.POST.get("name", "").strip()
        if not name:
            context = _build_board_context(request.user, board, request.session)
            return render(request, "boards/_filter_response.html", context)
        filter_config = _board_filter_for(board, request.session)
        SavedFilter.objects.update_or_create(
            board=board,
            name=name,
            defaults={"filter_config": filter_config},
        )
        context = _build_board_context(request.user, board, request.session)
        return render(request, "boards/_filter_response.html", context)


class SavedFilterDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        saved_filter = get_object_or_404(SavedFilter.objects.select_related("board"), pk=pk)
        if not user_can_access_board(request.user, saved_filter.board):
            raise Http404()
        board = saved_filter.board
        saved_filter.delete()
        context = _build_board_context(request.user, board, request.session)
        return render(request, "boards/_filter_response.html", context)
