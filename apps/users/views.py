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


class HomeView(LoginRequiredMixin, View):
    """Where sign-in and the logo land: the person's chosen default view."""

    def get(self, request):
        user = request.user
        return redirect(user.VIEW_URL_NAMES.get(user.default_view, "list:list"))


class SettingsGeneralView(LoginRequiredMixin, View):
    def get(self, request):
        from apps.accounts.linking import settings_connection_context
        from apps.tasks.models import TaskStatus
        from apps.users.selectors import primary_email
        from apps.workspaces.access import active_workspace

        workspace = active_workspace(request)
        statuses = TaskStatus.objects.filter(workspace=workspace)

        context = {
            "statuses": statuses,
            "default_status_id": _default_status_id(request.user, workspace),
            "timezones": _available_timezones(),
            "view_choices": request.user.VIEW_CHOICES,
            "signed_in_email": primary_email(request.user),
            "active_tab": "general",
        }
        context.update(settings_connection_context(request.user))
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
        default_view = request.POST.get("default_view", "")
        if default_view in user.VIEW_URL_NAMES:
            user.default_view = default_view
            update_fields.append("default_view")
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


class TaskExportView(LoginRequiredMixin, View):
    """Download the active workspace's tasks as an iCalendar (.ics) file."""

    def get(self, request):
        from apps.tasks.ical import export_response
        from apps.workspaces.access import active_workspace

        return export_response(active_workspace(request))


class TaskImportView(LoginRequiredMixin, View):
    """Import an .ics file into the active workspace, in two steps: posting a
    file shows a preview (a dry run), and confirming it imports. The preview
    carries the file's text in a hidden field, so nothing is kept between the
    two requests and the confirm step works it out again from scratch."""

    def get(self, request):
        return redirect(reverse("users:settings"))

    def post(self, request):
        from apps.tasks import ical_import
        from apps.tasks.models import TaskActivity
        from apps.workspaces.access import active_workspace, ensure_can_write

        ensure_can_write(request)
        workspace = active_workspace(request)

        confirm = request.POST.get("confirm") == "1"
        if confirm:
            text = request.POST.get("ics", "")
            filename = request.POST.get("filename", "")
        else:
            upload = request.FILES.get("file")
            if upload is None:
                messages.error(request, "Choose an .ics file to import.")
                return redirect(reverse("users:settings"))
            filename = upload.name
            if upload.size > ical_import.MAX_BYTES:
                messages.error(request, "That file is too big. The limit is 2 MB.")
                return redirect(reverse("users:settings"))
            try:
                text = upload.read().decode("utf-8-sig")
            except UnicodeDecodeError:
                messages.error(request, "That file isn't UTF-8 text, so it can't be an .ics file.")
                return redirect(reverse("users:settings"))

        try:
            result = ical_import.import_ics(
                text,
                workspace=workspace,
                user=request.user,
                dry_run=not confirm,
                source=TaskActivity.SOURCE_WEB,
                floating_tz=ical_import.user_zone(request.user),
            )
        except ical_import.IcsImportError as e:
            messages.error(request, str(e))
            return redirect(reverse("users:settings"))

        if confirm:
            messages.success(request, f"Imported {filename or 'the file'}: {result.summary}.")
            for warning in result.warnings[:5]:
                messages.warning(request, warning)
            if len(result.warnings) > 5:
                messages.warning(request, f"…and {len(result.warnings) - 5} more warnings.")
            return redirect(reverse("users:settings"))

        context = {
            "result": result,
            "ics": text,
            "filename": filename,
            "active_tab": "general",
        }
        context.update(_hero_stats(workspace))
        return render(request, "users/settings/import_preview.html", context)


def _saved_filters_with_labels(board):
    from apps.boards.filtering import parse_lane_key
    from apps.tasks.models import TaskStatus

    statuses_by_pk = {
        s.pk: s.name for s in TaskStatus.objects.filter(workspace_id=board.workspace_id)
    }
    columns_by_pk = {column.pk: column.label for column in board.columns.all()}
    saved_filters = list(board.saved_filters.all())
    for sf in saved_filters:
        labels = []
        for key in sf.filter_config.get("hidden_lanes", []):
            kind, pk = parse_lane_key(key)
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


def _agents(user):
    from django.db.models import Max

    from apps.users.agents import agents_of

    return agents_of(user).annotate(last_used_at=Max("device_tokens__last_used_at"))


class SettingsApiView(LoginRequiredMixin, View):
    def get(self, request):
        context = {
            "active_tab": "api",
            "devices": request.user.device_tokens.all(),
            "agents": _agents(request.user),
        }
        return render(request, "users/settings/api.html", context)


class AgentCreateView(LoginRequiredMixin, View):
    def post(self, request):
        from django.core.exceptions import ValidationError

        from apps.users.agents import create_agent

        context = {}
        try:
            agent, raw = create_agent(parent=request.user, name=request.POST.get("name", ""))
        except ValidationError as exc:
            context["agent_error"] = exc.messages[0]
        else:
            context.update(new_token=raw, new_token_agent=agent)
        context["agents"] = _agents(request.user)
        return render(request, "users/_agents.html", context)


class AgentTokenView(LoginRequiredMixin, View):
    def post(self, request, pk):
        from apps.users.agents import agents_of, reissue_agent_token

        agent = get_object_or_404(agents_of(request.user), pk=pk)
        raw = reissue_agent_token(agent)
        context = {"new_token": raw, "new_token_agent": agent, "agents": _agents(request.user)}
        return render(request, "users/_agents.html", context)


class AgentDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        from apps.users.agents import agents_of

        agents_of(request.user).filter(pk=pk).delete()
        return render(request, "users/_agents.html", {"agents": _agents(request.user)})


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
