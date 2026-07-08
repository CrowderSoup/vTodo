from datetime import time

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View


def _hero_stats(user):
    from apps.tasks.models import TaskStatus
    from apps.boards.models import Board

    statuses_count = TaskStatus.objects.filter(user=user).count()
    try:
        board = Board.objects.get(user=user)
        columns_count = board.columns.count()
    except Board.DoesNotExist:
        columns_count = 0

    return {
        "statuses_count": statuses_count,
        "columns_count": columns_count,
        "daily_summary_on": user.daily_summary_enabled,
    }


class SettingsGeneralView(LoginRequiredMixin, View):
    def get(self, request):
        from apps.tasks.models import TaskStatus

        statuses = TaskStatus.objects.filter(user=request.user)

        context = {
            "statuses": statuses,
            "default_status_id": request.user.default_status_id,
            "active_tab": "general",
        }
        context.update(_hero_stats(request.user))
        return render(request, "users/settings/general.html", context)

    def post(self, request):
        from apps.tasks.models import TaskStatus

        user = request.user
        user.display_name = request.POST.get("display_name", "").strip()
        user.avatar_url = request.POST.get("avatar_url", "").strip()

        default_status = None
        default_status_id = request.POST.get("default_status", "").strip()
        if default_status_id.isdigit():
            default_status = TaskStatus.objects.filter(user=user, pk=int(default_status_id)).first()
        user.default_status = default_status

        user.save(update_fields=["display_name", "avatar_url", "default_status"])
        messages.success(request, "Settings saved.")
        return redirect(reverse("users:settings"))


class SettingsIntegrationsView(LoginRequiredMixin, View):
    def get(self, request):
        context = {"active_tab": "integrations"}
        context.update(_hero_stats(request.user))
        return render(request, "users/settings/integrations.html", context)

    def post(self, request):
        user = request.user
        user.daily_summary_enabled = request.POST.get("daily_summary_enabled") == "on"

        time_str = request.POST.get("daily_summary_time", "08:00")
        try:
            parts = time_str.split(":")
            user.daily_summary_time = time(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            pass

        user.save(update_fields=["daily_summary_enabled", "daily_summary_time"])
        messages.success(request, "Settings saved.")
        return redirect(reverse("users:settings-integrations"))


def _saved_filters_with_labels(board):
    columns_by_pk = {column.pk: column.label for column in board.columns.all()}
    saved_filters = list(board.saved_filters.all())
    for sf in saved_filters:
        sf.hidden_column_labels = [
            columns_by_pk.get(pk, "") for pk in sf.filter_config.get("hidden_columns", [])
        ]
    return saved_filters


class SettingsBoardView(LoginRequiredMixin, View):
    def get(self, request):
        from apps.tasks.models import TaskStatus
        from apps.boards.models import Board

        statuses = TaskStatus.objects.filter(user=request.user)
        try:
            board = Board.objects.get(user=request.user)
            columns = board.columns.all()
            saved_filters = _saved_filters_with_labels(board)
        except Board.DoesNotExist:
            columns = []
            saved_filters = []

        context = {
            "statuses": statuses,
            "columns": columns,
            "saved_filters": saved_filters,
            "default_status_id": request.user.default_status_id,
            "active_tab": "board",
        }
        context.update(_hero_stats(request.user))
        return render(request, "users/settings/board.html", context)


class SettingsApiView(LoginRequiredMixin, View):
    def get(self, request):
        context = {"active_tab": "api"}
        context.update(_hero_stats(request.user))
        return render(request, "users/settings/api.html", context)


class TaskStatusCreateView(LoginRequiredMixin, View):
    def post(self, request):
        from apps.tasks.models import TaskStatus

        name = request.POST.get("name", "").strip()
        is_done = request.POST.get("is_done") == "on"
        if not name:
            from django.http import HttpResponse
            return HttpResponse(status=422)

        order = TaskStatus.objects.filter(user=request.user).count()
        from django.utils.text import slugify
        slug = slugify(name)
        TaskStatus.objects.get_or_create(
            user=request.user,
            slug=slug,
            defaults={"name": name, "is_done": is_done, "order": order},
        )
        statuses = TaskStatus.objects.filter(user=request.user)
        return render(request, "users/_status_list.html", {
            "statuses": statuses,
            "default_status_id": request.user.default_status_id,
        })


class TaskStatusDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        from apps.tasks.models import TaskStatus

        status = get_object_or_404(TaskStatus, pk=pk, user=request.user)
        status.delete()
        request.user.refresh_from_db(fields=["default_status"])
        statuses = TaskStatus.objects.filter(user=request.user)
        return render(request, "users/_status_list.html", {
            "statuses": statuses,
            "default_status_id": request.user.default_status_id,
        })


class ColumnCreateView(LoginRequiredMixin, View):
    def post(self, request):
        from apps.boards.models import Board, Column

        label = request.POST.get("label", "").strip()
        if not label:
            from django.http import HttpResponse
            return HttpResponse(status=422)

        statuses_raw = request.POST.get("statuses", "")
        tags_raw = request.POST.get("tags", "")
        due = request.POST.get("due") or None

        statuses = [s.strip() for s in statuses_raw.split(",") if s.strip()]
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

        board = get_object_or_404(Board, user=request.user)
        order = board.columns.count()
        Column.objects.create(
            board=board,
            label=label,
            filter_config={"statuses": statuses, "tags": tags, "due": due},
            order=order,
        )
        columns = board.columns.all()
        return render(request, "users/_column_list.html", {"columns": columns})


class ColumnDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        from apps.boards.models import Board, Column

        board = get_object_or_404(Board, user=request.user)
        column = get_object_or_404(Column, pk=pk, board=board)
        column.delete()
        columns = board.columns.all()
        return render(request, "users/_column_list.html", {"columns": columns})


class SavedViewDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        from apps.boards.models import Board, SavedFilter

        board = get_object_or_404(Board, user=request.user)
        saved_filter = get_object_or_404(SavedFilter, pk=pk, board=board)
        saved_filter.delete()
        saved_filters = _saved_filters_with_labels(board)
        return render(request, "users/_saved_views_list.html", {"saved_filters": saved_filters})


class ApiTokenView(LoginRequiredMixin, View):
    def get(self, request):
        from rest_framework.authtoken.models import Token

        token, _ = Token.objects.get_or_create(user=request.user)
        return render(request, "users/_api_token.html", {"api_token": token.key})


class ApiTokenRegenerateView(LoginRequiredMixin, View):
    def post(self, request):
        from rest_framework.authtoken.models import Token

        Token.objects.filter(user=request.user).delete()
        token = Token.objects.create(user=request.user)
        return render(request, "users/_api_token.html", {"api_token": token.key})
