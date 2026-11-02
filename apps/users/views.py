from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View


def _hero_stats(workspace):
    from apps.boards.models import Board
    from apps.tasks.models import TaskStatus

    statuses_count = TaskStatus.objects.filter(workspace=workspace).count()
    try:
        columns_count = workspace.board.columns.count()
    except Board.DoesNotExist:
        columns_count = 0

    return {
        "statuses_count": statuses_count,
        "custom_lanes_count": columns_count,
    }


def _available_timezones():
    from zoneinfo import available_timezones

    return sorted(available_timezones())


def _default_status_id(user, workspace):
    if workspace.default_status_id:
        return workspace.default_status_id
    from apps.workspaces.models import Workspace

    if workspace.kind == Workspace.KIND_PERSONAL and workspace.owner_id == user.pk:
        return user.default_status_id
    return None


class SettingsGeneralView(LoginRequiredMixin, View):
    def get(self, request):
        from apps.tasks.models import TaskStatus
        from apps.users.selectors import primary_email
        from apps.workspaces.access import active_workspace

        workspace = active_workspace(request)
        statuses = TaskStatus.objects.filter(workspace=workspace)

        context = {
            "statuses": statuses,
            "default_status_id": _default_status_id(request.user, workspace),
            "timezones": _available_timezones(),
            "signed_in_email": primary_email(request.user),
            "active_tab": "general",
        }
        context.update(_hero_stats(workspace))
        return render(request, "users/settings/general.html", context)

    def post(self, request):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        from django.db import transaction

        from apps.tasks.models import TaskStatus
        from apps.workspaces.access import active_workspace
        from apps.workspaces.models import Workspace

        user = request.user
        workspace = active_workspace(request)
        display_name = request.POST.get("display_name", "").strip()

        tzname = request.POST.get("timezone", "").strip()
        if tzname:
            try:
                ZoneInfo(tzname)
            except (ZoneInfoNotFoundError, ValueError):
                messages.error(request, "That's not a recognized timezone.")
                return redirect(reverse("users:settings"))

        update_fields = ["display_name"]
        user.display_name = display_name
        if tzname:
            user.timezone = tzname
            update_fields.append("timezone")

        update_default_status = (
            request.workspace_membership.can_admin() and "default_status" in request.POST
        )
        default_status = None
        if update_default_status:
            default_status_id = request.POST.get("default_status", "").strip()
            if default_status_id.isdigit():
                default_status = TaskStatus.objects.filter(
                    workspace=workspace, pk=int(default_status_id)
                ).first()

        with transaction.atomic():
            if update_default_status:
                workspace.default_status = default_status
                workspace.save(update_fields=["default_status"])
                if workspace.kind == Workspace.KIND_PERSONAL and workspace.owner_id == user.pk:
                    user.default_status = default_status
                    update_fields.append("default_status")
            user.save(update_fields=update_fields)

        messages.success(request, "Settings saved.")
        return redirect(reverse("users:settings"))


def _saved_filters_with_labels(board):
    from apps.boards.views import _parse_lane_key
    from apps.tasks.models import TaskStatus

    statuses_by_pk = {
        s.pk: s.name for s in TaskStatus.objects.filter(workspace_id=board.workspace_id)
    }
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


def _member_rows(workspace):
    memberships = (
        workspace.memberships.select_related("user")
        .prefetch_related("user__email_identities")
        .order_by("joined_at")
    )
    rows = []
    for membership in memberships:
        verified = sorted(
            (item for item in membership.user.email_identities.all() if item.verified),
            key=lambda item: item.created_at,
        )
        identity = verified[0] if verified else None
        email = identity.email if identity else ""
        rows.append({
            "membership": membership,
            "email": email,
            "name": membership.user.display_name or email or membership.user.username,
        })
    return rows


class SettingsBoardView(LoginRequiredMixin, View):
    def get(self, request):
        from apps.boards.selectors import resolve_board
        from apps.tasks.selectors import visible_statuses_qs
        from apps.workspaces.access import active_workspace

        workspace = active_workspace(request)
        board = resolve_board(request.user)
        statuses = list(visible_statuses_qs(request.user).order_by("order"))
        columns = list(board.columns.all())
        saved_filters = _saved_filters_with_labels(board)

        context = {
            "statuses": statuses,
            "board": board,
            "columns": columns,
            "saved_filters": saved_filters,
            "default_status_id": _default_status_id(request.user, workspace),
            "members": _member_rows(workspace),
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
        context = {"active_tab": "api", "devices": request.user.device_tokens.all()}
        return render(request, "users/settings/api.html", context)


class DeviceTokenRevokeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        request.user.device_tokens.filter(pk=pk).delete()
        return render(request, "users/_device_tokens.html", {"devices": request.user.device_tokens.all()})


def _status_list_context(request):
    from apps.tasks.selectors import visible_statuses_qs
    from apps.workspaces.access import active_workspace

    workspace = active_workspace(request)
    return {
        "statuses": list(visible_statuses_qs(request.user).order_by("order")),
        "default_status_id": _default_status_id(request.user, workspace),
    }


class TaskStatusCreateView(LoginRequiredMixin, View):
    def post(self, request):
        from django.http import HttpResponse
        from django.utils.text import slugify

        from apps.tasks.models import TaskStatus
        from apps.workspaces.access import active_workspace, ensure_can_admin

        ensure_can_admin(request)
        name = request.POST.get("name", "").strip()
        is_done = request.POST.get("is_done") == "on"
        if not name:
            return HttpResponse(status=422)

        workspace = active_workspace(request)
        slug = slugify(name)
        order = TaskStatus.objects.filter(workspace=workspace).count()
        TaskStatus.objects.get_or_create(
            workspace=workspace,
            slug=slug,
            defaults={"user": request.user, "name": name, "is_done": is_done, "order": order},
        )

        return render(request, "users/_status_list.html", _status_list_context(request))


class TaskStatusDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        from apps.tasks.models import TaskStatus
        from apps.workspaces.access import active_workspace, ensure_can_admin

        ensure_can_admin(request)
        status = get_object_or_404(TaskStatus, workspace=active_workspace(request), pk=pk)

        status.delete()
        request.user.refresh_from_db(fields=["default_status"])
        return render(request, "users/_status_list.html", _status_list_context(request))


class TaskStatusColorUpdateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        import re

        from apps.tasks.models import TaskStatus
        from apps.workspaces.access import active_workspace, ensure_can_admin

        ensure_can_admin(request)
        status = get_object_or_404(TaskStatus, workspace=active_workspace(request), pk=pk)

        color = request.POST.get("color", "").strip()
        if color and not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            return HttpResponse(status=422)

        status.color = color
        status.save(update_fields=["color"])

        return render(request, "users/_status_list.html", _status_list_context(request))


class ColumnCreateView(LoginRequiredMixin, View):
    def post(self, request):
        from apps.boards.models import Column
        from apps.boards.selectors import resolve_board
        from apps.workspaces.access import ensure_can_admin

        ensure_can_admin(request)
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
        from apps.workspaces.access import active_workspace, ensure_can_admin

        ensure_can_admin(request)
        column = get_object_or_404(Column.objects.select_related("board"), pk=pk)
        if (
            not user_can_access_board(request.user, column.board)
            or column.board.workspace_id != active_workspace(request).pk
        ):
            raise Http404()
        board = column.board
        column.delete()
        columns = list(board.columns.all())
        return render(request, "users/_column_list.html", {"columns": columns})


class SavedViewDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        from apps.boards.models import SavedFilter
        from apps.boards.selectors import user_can_access_board
        from apps.workspaces.access import active_workspace, ensure_can_admin

        ensure_can_admin(request)
        saved_filter = get_object_or_404(SavedFilter.objects.select_related("board"), pk=pk)
        if (
            not user_can_access_board(request.user, saved_filter.board)
            or saved_filter.board.workspace_id != active_workspace(request).pk
        ):
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
