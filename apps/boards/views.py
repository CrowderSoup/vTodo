import json
import re
import markdown as md
from datetime import date, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views import View

from apps.tasks.models import Task, TaskComment, TaskStatus

from .models import Board, Column, SavedFilter

TASK_CHECKBOX_PATTERN = re.compile(r"<(?P<tag>li|p)>\[(?P<state>[xX ])\]\s*(?P<body>.*?)</(?P=tag)>", re.DOTALL)


def _task_matches_column(task, filter_config):
    statuses = filter_config.get("statuses", [])
    tags = filter_config.get("tags", [])
    due = filter_config.get("due")

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


def _status_context(user):
    statuses = list(TaskStatus.objects.filter(user=user))
    done_slug = next((s.slug for s in statuses if s.is_done), "done")
    active_slug = next((s.slug for s in statuses if not s.is_done), "todo")
    return statuses, done_slug, active_slug


def _task_render_context(user, task):
    statuses, done_slug, active_slug = _status_context(user)
    return {
        "task": task,
        "statuses": statuses,
        "done_slug": done_slug,
        "active_slug": active_slug,
        "today": timezone.localdate(),
    }


def _build_board_context(user, session=None):
    board = get_object_or_404(Board, user=user)
    columns = list(board.columns.all())
    today = timezone.localdate()

    board_filter = (session.get("board_filter") or {}) if session else {}
    filter_tags = board_filter.get("tags", [])
    filter_due = board_filter.get("due", "").strip()
    hidden_column_pks = set(board_filter.get("hidden_columns", []))

    all_tasks = list(Task.objects.filter(user=user, is_archived=False).order_by("order", "created_at"))
    tasks = list(all_tasks)

    if filter_tags:
        tasks = [t for t in tasks if all(tag in t.tags for tag in filter_tags)]
    if filter_due:
        if filter_due == "overdue":
            tasks = [t for t in tasks if t.due_date and t.due_date < today]
        elif filter_due == "today":
            tasks = [t for t in tasks if t.due_date == today]
        elif filter_due == "this_week":
            end = today + timedelta(days=7)
            tasks = [t for t in tasks if t.due_date and today <= t.due_date <= end]

    statuses, done_slug, active_slug = _status_context(user)

    hidden_columns = []
    claimed = set()
    columns_with_tasks = []
    for column in columns:
        if column.pk in hidden_column_pks:
            hidden_columns.append(column)
            continue
        col_tasks = []
        for task in tasks:
            if task.pk not in claimed and _task_matches_column(task, column.filter_config):
                col_tasks.append(task)
                claimed.add(task.pk)
        columns_with_tasks.append((column, col_tasks, column.default_status(user)))

    saved_filters = list(board.saved_filters.all())
    active_saved_filter_name = None
    current_config = {"tags": filter_tags, "due": filter_due, "hidden_columns": list(hidden_column_pks)}
    for sf in saved_filters:
        sf_config = sf.filter_config
        if (
            sorted(sf_config.get("tags", [])) == sorted(current_config["tags"])
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
        "active_filter": {"tags": filter_tags, "due": filter_due, "hidden_columns": hidden_columns},
        "saved_filters": saved_filters,
        "active_saved_filter_name": active_saved_filter_name,
        "today": today,
        "total_task_count": len(all_tasks),
        "visible_task_count": len(tasks),
        "done_task_count": sum(1 for task in all_tasks if task.completed_at),
        "due_today_count": sum(1 for task in tasks if task.due_date == today and not task.completed_at),
        "overdue_count": sum(1 for task in tasks if task.due_date and task.due_date < today and not task.completed_at),
        "active_filter_count": len(filter_tags) + len(hidden_column_pks) + (1 if filter_due else 0),
    }


class BoardView(LoginRequiredMixin, View):
    def get(self, request):
        context = _build_board_context(request.user, request.session)
        return render(request, "boards/board.html", context)


class BoardFilterView(LoginRequiredMixin, View):
    def post(self, request):
        tags = request.POST.getlist("tags")
        due = request.POST.get("due", "").strip()
        hidden_columns = [int(pk) for pk in request.POST.getlist("hidden_columns") if pk.isdigit()]
        request.session["board_filter"] = {"tags": tags, "due": due, "hidden_columns": hidden_columns}
        request.session.modified = True
        context = _build_board_context(request.user, request.session)
        return render(request, "boards/_filter_response.html", context)


class BoardFilterAddTagView(LoginRequiredMixin, View):
    """Add a single tag to the active filter without replacing existing ones."""

    def post(self, request):
        tag = request.POST.get("tag", "").strip()
        board_filter = request.session.get("board_filter") or {}
        current_tags = board_filter.get("tags", [])
        due = board_filter.get("due", "")
        hidden_columns = board_filter.get("hidden_columns", [])
        if tag and tag not in current_tags:
            current_tags = current_tags + [tag]
        request.session["board_filter"] = {"tags": current_tags, "due": due, "hidden_columns": hidden_columns}
        request.session.modified = True
        context = _build_board_context(request.user, request.session)
        return render(request, "boards/_filter_response.html", context)


class ColumnHideView(LoginRequiredMixin, View):
    """Add a column to the session hidden-columns filter."""

    def post(self, request, pk):
        board = get_object_or_404(Board, user=request.user)
        column = get_object_or_404(Column, pk=pk, board=board)
        board_filter = request.session.get("board_filter") or {}
        hidden = board_filter.get("hidden_columns", [])
        if column.pk not in hidden:
            hidden = hidden + [column.pk]
        request.session["board_filter"] = {**board_filter, "hidden_columns": hidden}
        request.session.modified = True
        context = _build_board_context(request.user, request.session)
        return render(request, "boards/_filter_response.html", context)


class ColumnReorderView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            order = data.get("order", [])
        except (json.JSONDecodeError, AttributeError):
            return HttpResponse(status=400)

        board = get_object_or_404(Board, user=request.user)
        columns = {c.pk: c for c in board.columns.all()}
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

        tasks = {t.pk: t for t in Task.objects.filter(user=request.user, pk__in=order)}
        for i, pk in enumerate(order):
            if pk in tasks:
                tasks[pk].order = i
                tasks[pk].save(update_fields=["order"])

        return HttpResponse(status=204)


class TaskCreateView(LoginRequiredMixin, View):
    def post(self, request):
        status = request.POST.get("status", "").strip()
        title = request.POST.get("title", "").strip()

        if not title:
            return HttpResponse(status=422)

        valid_slugs = list(TaskStatus.objects.filter(user=request.user).values_list("slug", flat=True))
        if status not in valid_slugs:
            status = valid_slugs[0] if valid_slugs else "todo"

        task = Task.objects.create(user=request.user, title=title, status=status)
        return render(request, "partials/task_card.html", _task_render_context(request.user, task))


class TaskUpdateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk, user=request.user)
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
        task = get_object_or_404(Task, pk=pk, user=request.user)
        new_status = request.POST.get("new_status", "")

        valid_slugs = list(TaskStatus.objects.filter(user=request.user).values_list("slug", flat=True))
        if new_status not in valid_slugs:
            return HttpResponse(status=422)

        task.status = new_status
        is_done = TaskStatus.objects.filter(user=request.user, slug=new_status, is_done=True).exists()
        if is_done and not task.completed_at:
            task.completed_at = timezone.now()
            task.save(update_fields=["status", "completed_at", "updated_at"])
            task.spawn_recurrence(completion_date=task.completed_at.date())
        else:
            if not is_done:
                task.completed_at = None
            task.save(update_fields=["status", "completed_at", "updated_at"])

        context = _build_board_context(request.user, request.session)
        return render(request, "boards/_columns.html", context)


class TaskDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk, user=request.user)
        task.delete()
        return HttpResponse("")


class ColumnArchiveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        board = get_object_or_404(Board, user=request.user)
        column = get_object_or_404(Column, pk=pk, board=board)

        # Mirror the claimed-task logic from _build_board_context to find exactly
        # which tasks are visible in this column.
        all_tasks = list(Task.objects.filter(user=request.user, is_archived=False).order_by("order", "created_at"))
        claimed = set()
        to_archive = []
        for col in board.columns.all():
            for task in all_tasks:
                if task.pk not in claimed and _task_matches_column(task, col.filter_config):
                    if col.pk == column.pk:
                        to_archive.append(task.pk)
                    claimed.add(task.pk)

        Task.objects.filter(pk__in=to_archive).update(is_archived=True)

        context = _build_board_context(request.user, request.session)
        return render(request, "boards/_columns.html", context)


class TaskDetailView(LoginRequiredMixin, View):
    """Return the read-only task card partial. Used by the edit form's Cancel button."""

    def get(self, request, pk):
        task = get_object_or_404(Task, pk=pk, user=request.user)
        return render(request, "partials/task_card.html", _task_render_context(request.user, task))


class TaskEditView(LoginRequiredMixin, View):
    """Return the edit form partial. Triggered by clicking the task title."""

    def get(self, request, pk):
        task = get_object_or_404(Task, pk=pk, user=request.user)
        return render(request, "partials/task_edit_form.html", {"task": task})


class TaskPanelView(LoginRequiredMixin, View):
    """Return the panel read-mode content."""

    def get(self, request, pk):
        task = get_object_or_404(Task, pk=pk, user=request.user)
        context = _task_render_context(request.user, task)
        context.update({
            "notes_html": _render_markdown(task.notes) if task.notes else "",
            "comments": _render_comments(task),
        })
        return render(request, "partials/task_panel_content.html", context)


class TaskPanelEditView(LoginRequiredMixin, View):
    """Return the panel edit-mode content."""

    def get(self, request, pk):
        task = get_object_or_404(Task, pk=pk, user=request.user)
        context = _task_render_context(request.user, task)
        return render(request, "partials/task_panel_edit.html", context)


class TaskPanelUpdateView(LoginRequiredMixin, View):
    """Save task from the panel; returns updated panel read-mode + OOB card update."""

    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk, user=request.user)
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

        context = _task_render_context(request.user, task)
        context.update({
            "notes_html": _render_markdown(task.notes) if task.notes else "",
        })
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
        task = get_object_or_404(Task, pk=pk, user=request.user)
        body = request.POST.get("body", "").strip()
        if body:
            TaskComment.objects.create(task=task, body=body)
        return render(request, "partials/task_comments.html", {
            "task": task,
            "comments": _render_comments(task),
        })


class TaskCommentDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk, comment_pk):
        task = get_object_or_404(Task, pk=pk, user=request.user)
        comment = get_object_or_404(TaskComment, pk=comment_pk, task=task)
        comment.delete()
        return render(request, "partials/task_comments.html", {
            "task": task,
            "comments": _render_comments(task),
        })


class SavedFilterLoadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        board = get_object_or_404(Board, user=request.user)
        saved_filter = get_object_or_404(SavedFilter, pk=pk, board=board)
        request.session["board_filter"] = saved_filter.filter_config
        request.session.modified = True
        context = _build_board_context(request.user, request.session)
        return render(request, "boards/_filter_response.html", context)


class SavedFilterSaveView(LoginRequiredMixin, View):
    def post(self, request):
        board = get_object_or_404(Board, user=request.user)
        name = request.POST.get("name", "").strip()
        if not name:
            context = _build_board_context(request.user, request.session)
            return render(request, "boards/_filter_response.html", context)
        filter_config = request.session.get("board_filter") or {}
        SavedFilter.objects.update_or_create(
            board=board,
            name=name,
            defaults={"filter_config": filter_config},
        )
        context = _build_board_context(request.user, request.session)
        return render(request, "boards/_filter_response.html", context)


class SavedFilterDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        board = get_object_or_404(Board, user=request.user)
        saved_filter = get_object_or_404(SavedFilter, pk=pk, board=board)
        saved_filter.delete()
        context = _build_board_context(request.user, request.session)
        return render(request, "boards/_filter_response.html", context)
