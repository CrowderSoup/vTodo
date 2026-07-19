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
        "columns_count": columns_count,
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


def _resolve_settings_board(user, team_id_str):
    """The board the Settings > Board page should show: the team board named by
    team_id_str if it's valid and the user belongs to it, else the personal board."""
    from apps.boards.selectors import resolve_board

    if team_id_str and team_id_str.isdigit():
        try:
            return resolve_board(user, int(team_id_str))
        except Http404:
            pass
    return resolve_board(user, None)


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
        from apps.tasks.selectors import all_visible_statuses_qs, user_teams_qs

        board = _resolve_settings_board(request.user, request.GET.get("team", "").strip())
        statuses = all_visible_statuses_qs(request.user)
        columns = list(board.columns.all())
        saved_filters = _saved_filters_with_labels(board)

        context = {
            "statuses": statuses,
            "board": board,
            "columns": columns,
            "saved_filters": saved_filters,
            "default_status_id": request.user.default_status_id,
            "user_teams": list(user_teams_qs(request.user)),
            "active_tab": "board",
        }
        context.update(_hero_stats(request.user))
        return render(request, "users/settings/board.html", context)


class SettingsApiView(LoginRequiredMixin, View):
    def get(self, request):
        context = {"active_tab": "api"}
        context.update(_hero_stats(request.user))
        return render(request, "users/settings/api.html", context)


class SettingsTeamsView(LoginRequiredMixin, View):
    def get(self, request):
        from apps.teams.models import TeamMembership

        memberships = (
            TeamMembership.objects.filter(user=request.user)
            .select_related("team")
            .prefetch_related("team__memberships__user", "team__invites")
        )
        teams = []
        for membership in memberships:
            team = membership.team
            teams.append({
                "team": team,
                "role": membership.role,
                "is_owner": membership.role == TeamMembership.ROLE_OWNER,
                "members": list(team.memberships.select_related("user")),
                "pending_invites": [inv for inv in team.invites.all() if inv.is_valid],
            })

        context = {"teams": teams, "active_tab": "teams"}
        context.update(_hero_stats(request.user))
        return render(request, "users/settings/teams.html", context)


def _resolve_owned_team(user, team_id_str):
    """Returns None (personal) or a Team the user belongs to, else False for an invalid id."""
    if not team_id_str:
        return None
    from apps.tasks.selectors import user_teams_qs

    if not team_id_str.isdigit():
        return False
    team = user_teams_qs(user).filter(pk=int(team_id_str)).first()
    return team if team else False


class TaskStatusCreateView(LoginRequiredMixin, View):
    def post(self, request):
        from django.http import HttpResponse
        from django.utils.text import slugify

        from apps.tasks.models import TaskStatus
        from apps.tasks.selectors import all_visible_statuses_qs

        team = _resolve_owned_team(request.user, request.POST.get("team", "").strip())
        if team is False:
            return HttpResponse(status=422)

        name = request.POST.get("name", "").strip()
        is_done = request.POST.get("is_done") == "on"
        if not name:
            return HttpResponse(status=422)

        slug = slugify(name)
        if team:
            order = TaskStatus.objects.filter(team=team).count()
            TaskStatus.objects.get_or_create(
                team=team, slug=slug, defaults={"name": name, "is_done": is_done, "order": order}
            )
        else:
            order = TaskStatus.objects.filter(user=request.user, team__isnull=True).count()
            TaskStatus.objects.get_or_create(
                user=request.user, slug=slug, defaults={"name": name, "is_done": is_done, "order": order}
            )

        return render(request, "users/_status_list.html", {
            "statuses": all_visible_statuses_qs(request.user),
            "default_status_id": request.user.default_status_id,
        })


class TaskStatusDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        from django.db.models import Q

        from apps.tasks.models import TaskStatus
        from apps.tasks.selectors import all_visible_statuses_qs, user_team_ids

        status = get_object_or_404(
            TaskStatus.objects.filter(
                Q(user=request.user, team__isnull=True) | Q(team_id__in=user_team_ids(request.user))
            ),
            pk=pk,
        )

        status.delete()
        request.user.refresh_from_db(fields=["default_status"])
        return render(request, "users/_status_list.html", {
            "statuses": all_visible_statuses_qs(request.user),
            "default_status_id": request.user.default_status_id,
        })


class ColumnCreateView(LoginRequiredMixin, View):
    def post(self, request):
        from apps.boards.models import Column

        label = request.POST.get("label", "").strip()
        if not label:
            return HttpResponse(status=422)

        team = _resolve_owned_team(request.user, request.POST.get("team", "").strip())
        if team is False:
            return HttpResponse(status=422)
        board = _resolve_settings_board(request.user, str(team.pk) if team else "")

        assignee = request.POST.get("assignee", "any").strip() or "any"

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
                "assignee": assignee,
            },
            order=order,
        )
        columns = list(board.columns.all())
        return render(request, "users/_column_list.html", {"columns": columns})


class ColumnStatusOptionsView(LoginRequiredMixin, View):
    def get(self, request):
        from apps.tasks.selectors import visible_statuses_qs

        team = _resolve_owned_team(request.user, request.GET.get("team", "").strip())
        if team is False:
            return HttpResponse(status=422)

        statuses = visible_statuses_qs(request.user, team=team)
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
