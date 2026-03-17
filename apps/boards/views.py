from datetime import date, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views import View

from apps.tasks.models import Task, TaskStatus

from .models import Board, Column


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


def _build_board_context(user):
    board = get_object_or_404(Board, user=user)
    columns = list(board.columns.all())
    tasks = list(Task.objects.filter(user=user).order_by("order", "created_at"))
    statuses, done_slug, active_slug = _status_context(user)

    claimed = set()
    columns_with_tasks = []
    for column in columns:
        col_tasks = []
        for task in tasks:
            if task.pk not in claimed and _task_matches_column(task, column.filter_config):
                col_tasks.append(task)
                claimed.add(task.pk)
        columns_with_tasks.append((column, col_tasks, column.default_status(user)))

    return {
        "board": board,
        "columns_with_tasks": columns_with_tasks,
        "statuses": statuses,
        "done_slug": done_slug,
        "active_slug": active_slug,
    }


class BoardView(LoginRequiredMixin, View):
    def get(self, request):
        context = _build_board_context(request.user)
        return render(request, "boards/board.html", context)


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
        statuses, done_slug, active_slug = _status_context(request.user)
        return render(request, "partials/task_card.html", {
            "task": task,
            "statuses": statuses,
            "done_slug": done_slug,
            "active_slug": active_slug,
        })


class TaskUpdateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk, user=request.user)
        title = request.POST.get("title", "").strip()
        notes = request.POST.get("notes", "")
        due_date = request.POST.get("due_date") or None

        tags_raw = request.POST.get("tags", "")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

        if title:
            task.title = title
        task.notes = notes
        task.due_date = due_date
        task.tags = tags
        task.save(update_fields=["title", "notes", "due_date", "tags", "updated_at"])

        statuses, done_slug, active_slug = _status_context(request.user)
        return render(request, "partials/task_card.html", {
            "task": task,
            "statuses": statuses,
            "done_slug": done_slug,
            "active_slug": active_slug,
        })


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
        elif not is_done:
            task.completed_at = None
        task.save(update_fields=["status", "completed_at", "updated_at"])

        context = _build_board_context(request.user)
        return render(request, "boards/_columns.html", context)


class TaskDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk, user=request.user)
        task.delete()
        return HttpResponse("")


class TaskDetailView(LoginRequiredMixin, View):
    """Return the read-only task card partial. Used by the edit form's Cancel button."""

    def get(self, request, pk):
        task = get_object_or_404(Task, pk=pk, user=request.user)
        statuses, done_slug, active_slug = _status_context(request.user)
        return render(request, "partials/task_card.html", {
            "task": task,
            "statuses": statuses,
            "done_slug": done_slug,
            "active_slug": active_slug,
        })


class TaskEditView(LoginRequiredMixin, View):
    """Return the edit form partial. Triggered by clicking the task title."""

    def get(self, request, pk):
        task = get_object_or_404(Task, pk=pk, user=request.user)
        return render(request, "partials/task_edit_form.html", {"task": task})
