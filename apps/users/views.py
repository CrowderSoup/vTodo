from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
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
        "custom_lanes_count": columns_count,
    }


def _available_timezones():
    from zoneinfo import available_timezones

    return sorted(available_timezones())


class SettingsGeneralView(LoginRequiredMixin, View):
    def get(self, request):
        from apps.tasks.models import TaskStatus
        from apps.users.selectors import primary_email

        statuses = TaskStatus.objects.filter(user=request.user)

        context = {
            "statuses": statuses,
            "default_status_id": request.user.default_status_id,
            "timezones": _available_timezones(),
            "signed_in_email": primary_email(request.user),
            "active_tab": "general",
        }
        context.update(_hero_stats(request.user))
        return render(request, "users/settings/general.html", context)

    def post(self, request):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        from apps.tasks.models import TaskStatus

        user = request.user
        user.display_name = request.POST.get("display_name", "").strip()

        default_status = None
        default_status_id = request.POST.get("default_status", "").strip()
        if default_status_id.isdigit():
            default_status = TaskStatus.objects.filter(user=user, pk=int(default_status_id)).first()
        user.default_status = default_status

        tzname = request.POST.get("timezone", "").strip()
        if tzname:
            try:
                ZoneInfo(tzname)
            except (ZoneInfoNotFoundError, ValueError):
                messages.error(request, "That's not a recognized timezone.")
                return redirect(reverse("users:settings"))
            user.timezone = tzname

        user.save(update_fields=["display_name", "default_status", "timezone"])
        messages.success(request, "Settings saved.")
        return redirect(reverse("users:settings"))


def _saved_filters_with_labels(board):
    from apps.boards.views import _parse_lane_key
    from apps.tasks.selectors import visible_statuses_qs

    statuses_by_pk = {s.pk: s.name for s in visible_statuses_qs(board.user)}
    columns_by_pk = {column.pk: column.label for column in board.columns.all()}
    saved_filters = list(board.saved_filters.all())
    for sf in saved_filters:
        labels = []
        for key in sf.filter_config.get("hidden_lanes", []):
            kind, pk = _parse_lane_key(key)
            if kind == "status":
                labels.append(statuses_by_pk.get(pk, ""))
            elif kind == "column":
                labels.append(columns_by_pk.get(pk, ""))
        sf.hidden_column_labels = labels
    return saved_filters


class SettingsBoardView(LoginRequiredMixin, View):
    def get(self, request):
        from apps.boards.selectors import resolve_board
        from apps.tasks.selectors import visible_statuses_qs

        board = resolve_board(request.user)
        statuses = list(visible_statuses_qs(request.user).order_by("order"))
        columns = list(board.columns.all())
        saved_filters = _saved_filters_with_labels(board)

        context = {
            "statuses": statuses,
            "board": board,
            "columns": columns,
            "saved_filters": saved_filters,
            "default_status_id": request.user.default_status_id,
            "active_tab": "board",
        }
        return render(request, "users/settings/board.html", context)


class SettingsCalendarView(LoginRequiredMixin, View):
    def get(self, request):
        from apps.integrations.models import GoogleCalendarConnection

        connection = GoogleCalendarConnection.objects.filter(user=request.user).first()
        context = {"connection": connection, "active_tab": "calendar"}
        return render(request, "users/settings/calendar.html", context)


class SettingsApiView(LoginRequiredMixin, View):
    def get(self, request):
        context = {"active_tab": "api"}
        return render(request, "users/settings/api.html", context)


class TaskStatusCreateView(LoginRequiredMixin, View):
    def post(self, request):
        from django.http import HttpResponse
        from django.utils.text import slugify

        from apps.tasks.models import TaskStatus
        from apps.tasks.selectors import visible_statuses_qs

        name = request.POST.get("name", "").strip()
        is_done = request.POST.get("is_done") == "on"
        if not name:
            return HttpResponse(status=422)

        slug = slugify(name)
        order = TaskStatus.objects.filter(user=request.user).count()
        TaskStatus.objects.get_or_create(
            user=request.user, slug=slug, defaults={"name": name, "is_done": is_done, "order": order}
        )

        return render(request, "users/_status_list.html", {
            "statuses": list(visible_statuses_qs(request.user).order_by("order")),
            "default_status_id": request.user.default_status_id,
        })


class TaskStatusDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        from apps.tasks.models import TaskStatus
        from apps.tasks.selectors import visible_statuses_qs

        status = get_object_or_404(TaskStatus, user=request.user, pk=pk)

        status.delete()
        request.user.refresh_from_db(fields=["default_status"])
        return render(request, "users/_status_list.html", {
            "statuses": list(visible_statuses_qs(request.user).order_by("order")),
            "default_status_id": request.user.default_status_id,
        })


class TaskStatusColorUpdateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        import re

        from apps.tasks.models import TaskStatus
        from apps.tasks.selectors import visible_statuses_qs

        status = get_object_or_404(TaskStatus, user=request.user, pk=pk)

        color = request.POST.get("color", "").strip()
        if color and not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            return HttpResponse(status=422)

        status.color = color
        status.save(update_fields=["color"])

        return render(request, "users/_status_list.html", {
            "statuses": list(visible_statuses_qs(request.user).order_by("order")),
            "default_status_id": request.user.default_status_id,
        })


class ColumnCreateView(LoginRequiredMixin, View):
    def post(self, request):
        from apps.boards.models import Column
        from apps.boards.selectors import resolve_board

        label = request.POST.get("label", "").strip()
        if not label:
            return HttpResponse(status=422)

        board = resolve_board(request.user)

        tags_raw = request.POST.get("tags", "")
        due = request.POST.get("due") or None

        statuses = [s.strip() for s in request.POST.getlist("statuses") if s.strip()]
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

        order = board.columns.count()
        Column.objects.create(
            board=board,
            label=label,
            filter_config={
                "statuses": statuses,
                "tags": tags,
                "due": due,
            },
            order=order,
        )
        columns = list(board.columns.all())
        return render(request, "users/_column_list.html", {"columns": columns})


class ColumnStatusOptionsView(LoginRequiredMixin, View):
    def get(self, request):
        from apps.tasks.selectors import visible_statuses_qs

        statuses = visible_statuses_qs(request.user)
        return render(request, "users/_column_status_options.html", {"statuses": statuses})


class ColumnDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        from apps.boards.models import Column
        from apps.boards.selectors import user_can_access_board

        column = get_object_or_404(Column.objects.select_related("board"), pk=pk)
        if not user_can_access_board(request.user, column.board):
            raise Http404()
        board = column.board
        column.delete()
        columns = list(board.columns.all())
        return render(request, "users/_column_list.html", {"columns": columns})


class SavedViewDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        from apps.boards.models import SavedFilter
        from apps.boards.selectors import user_can_access_board

        saved_filter = get_object_or_404(SavedFilter.objects.select_related("board"), pk=pk)
        if not user_can_access_board(request.user, saved_filter.board):
            raise Http404()
        board = saved_filter.board
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
