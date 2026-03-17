from datetime import time

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View


class SettingsView(LoginRequiredMixin, View):
    def get(self, request):
        from apps.tasks.models import TaskStatus
        from apps.boards.models import Board, Column

        statuses = TaskStatus.objects.filter(user=request.user)
        try:
            board = Board.objects.get(user=request.user)
            columns = board.columns.all()
        except Board.DoesNotExist:
            columns = []

        return render(request, "users/settings.html", {
            "statuses": statuses,
            "columns": columns,
        })

    def post(self, request):
        user = request.user
        user.display_name = request.POST.get("display_name", "").strip()
        user.avatar_url = request.POST.get("avatar_url", "").strip()
        user.daily_summary_enabled = request.POST.get("daily_summary_enabled") == "on"

        time_str = request.POST.get("daily_summary_time", "08:00")
        try:
            parts = time_str.split(":")
            user.daily_summary_time = time(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            pass

        user.save(
            update_fields=[
                "display_name",
                "avatar_url",
                "daily_summary_enabled",
                "daily_summary_time",
            ]
        )
        messages.success(request, "Settings saved.")
        return redirect(reverse("users:settings"))


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
        return render(request, "users/_status_list.html", {"statuses": statuses})


class TaskStatusDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        from apps.tasks.models import TaskStatus

        status = get_object_or_404(TaskStatus, pk=pk, user=request.user)
        status.delete()
        statuses = TaskStatus.objects.filter(user=request.user)
        return render(request, "users/_status_list.html", {"statuses": statuses})


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
