from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps.teams.models import Team, TeamMembership

from .models import ExternalLink, SkylightConnection, SkylightMemberMapping
from .skylight.client import SkylightAPIError, SkylightAuthError, SkylightClient
from .skylight.client import refresh as skylight_refresh


def _owner_membership_or_404(user, team_pk):
    return get_object_or_404(
        TeamMembership, team_id=team_pk, user=user, role=TeamMembership.ROLE_OWNER
    )


def _calendar_label(attrs: dict) -> str:
    for key in ("email", "name", "title", "summary"):
        if attrs.get(key):
            return str(attrs[key])
    return "Connected calendar"


class SkylightConnectView(LoginRequiredMixin, View):
    def post(self, request, team_pk):
        _owner_membership_or_404(request.user, team_pk)
        team = get_object_or_404(Team, pk=team_pk)

        refresh_token = request.POST.get("refresh_token", "").strip()
        frame_id = request.POST.get("frame_id", "").strip()

        if not refresh_token or not frame_id:
            messages.error(request, "Refresh token and frame ID are both required.")
            return redirect(reverse("users:settings-teams"))

        try:
            result = skylight_refresh(refresh_token)
        except SkylightAuthError:
            messages.error(
                request,
                "Skylight rejected that refresh token. Make sure you copied the full "
                "\"refresh_token\" value (not the access_token) from a fresh login, and try again.",
            )
            return redirect(reverse("users:settings-teams"))
        except SkylightAPIError as exc:
            messages.error(request, f"Couldn't reach Skylight: {exc}")
            return redirect(reverse("users:settings-teams"))

        existing = SkylightConnection.objects.filter(team=team).first()
        keep_calendar = existing is not None and existing.frame_id == frame_id

        connection, _created = SkylightConnection.objects.update_or_create(
            team=team,
            defaults={
                "frame_id": frame_id,
                "connected_by": request.user,
                "is_active": True,
                **({} if keep_calendar else {"calendar_account_id": "", "calendar_id": ""}),
            },
        )
        connection.set_refresh_token(result["refresh_token"])
        connection.set_token(result["access_token"])
        connection.token_fetched_at = timezone.now()
        connection.save(
            update_fields=["refresh_token_encrypted", "token_encrypted", "token_fetched_at"]
        )

        if keep_calendar and connection.calendar_account_id:
            try:
                calendars = SkylightClient(connection).list_source_calendars()
            except (SkylightAuthError, SkylightAPIError):
                calendars = None
            # A stale calendar_account_id from a prior connection (e.g. the frame was
            # re-permissioned, or the source calendar was removed/re-added on
            # Skylight's side) otherwise survives silently and only surfaces later as
            # a sync-time 422 ("calendar_account_id is unknown"). Catch it here.
            if calendars is not None and not any(
                cal["id"] == connection.calendar_account_id for cal in calendars
            ):
                connection.calendar_account_id = ""
                connection.calendar_id = ""
                connection.save(update_fields=["calendar_account_id", "calendar_id"])
                messages.warning(
                    request,
                    "Your previously selected Skylight calendar is no longer available. "
                    "Please pick it again.",
                )

        messages.success(request, "Connected to Skylight.")
        if connection.is_ready:
            return redirect(reverse("users:settings-teams"))
        return redirect(reverse("integrations:skylight-select-calendar", args=[team_pk]))


class SkylightSelectCalendarView(LoginRequiredMixin, View):
    def get(self, request, team_pk):
        _owner_membership_or_404(request.user, team_pk)
        connection = get_object_or_404(SkylightConnection, team_id=team_pk)

        try:
            calendars = SkylightClient(connection).list_source_calendars()
        except (SkylightAuthError, SkylightAPIError) as exc:
            messages.error(request, f"Couldn't load Skylight calendars: {exc}")
            return redirect(reverse("users:settings-teams"))

        options = [
            {"id": cal["id"], "label": _calendar_label(cal.get("attributes", {})), "attrs": cal.get("attributes", {})}
            for cal in calendars
        ]
        return render(request, "integrations/skylight_select_calendar.html", {
            "team": connection.team,
            "calendars": options,
        })

    def post(self, request, team_pk):
        _owner_membership_or_404(request.user, team_pk)
        connection = get_object_or_404(SkylightConnection, team_id=team_pk)

        calendar_account_id = request.POST.get("calendar_account_id", "").strip()
        calendar_label = request.POST.get("calendar_label", "").strip()
        if not calendar_account_id:
            messages.error(request, "Pick a calendar to sync.")
            return redirect(reverse("integrations:skylight-select-calendar", args=[team_pk]))

        connection.calendar_account_id = calendar_account_id
        connection.calendar_id = calendar_label
        connection.save(update_fields=["calendar_account_id", "calendar_id"])

        messages.success(request, "Calendar selected. Map family members to team members below.")
        return redirect(reverse("integrations:skylight-mapping", args=[team_pk]))


class SkylightMemberMappingView(LoginRequiredMixin, View):
    def get(self, request, team_pk):
        _owner_membership_or_404(request.user, team_pk)
        connection = get_object_or_404(SkylightConnection, team_id=team_pk)

        try:
            categories = SkylightClient(connection).list_categories()
        except (SkylightAuthError, SkylightAPIError) as exc:
            messages.error(request, f"Couldn't load Skylight family members: {exc}")
            return redirect(reverse("users:settings-teams"))

        existing_by_category = {
            m.category_id: m for m in connection.member_mappings.all()
        }
        rows = []
        for category in categories:
            category_id = category["id"]
            label = category.get("attributes", {}).get("label") or category_id
            mapping = existing_by_category.get(category_id)
            rows.append({
                "category_id": category_id,
                "label": label,
                "mapped_user_id": mapping.user_id if mapping else None,
            })

        members = TeamMembership.objects.filter(team_id=team_pk).select_related("user")
        return render(request, "integrations/skylight_mapping.html", {
            "team": connection.team,
            "rows": rows,
            "members": members,
        })

    def post(self, request, team_pk):
        _owner_membership_or_404(request.user, team_pk)
        connection = get_object_or_404(SkylightConnection, team_id=team_pk)
        team_member_ids = set(
            TeamMembership.objects.filter(team_id=team_pk).values_list("user_id", flat=True)
        )

        for key, value in request.POST.items():
            if not key.startswith("category_label:"):
                continue
            category_id = key.split(":", 1)[1]
            user_field = f"user:{category_id}"
            user_id = request.POST.get(user_field, "").strip()
            try:
                user_id = int(user_id) if user_id else None
            except ValueError:
                user_id = None
            # Only ever map to someone on this team -- a stray/tampered id in the
            # POST body is silently treated as "unmapped" rather than trusted.
            if user_id is not None and user_id not in team_member_ids:
                user_id = None

            SkylightMemberMapping.objects.update_or_create(
                connection=connection,
                category_id=category_id,
                defaults={
                    "category_label": value,
                    "user_id": user_id,
                },
            )

        messages.success(request, "Saved family member mapping.")
        return redirect(reverse("users:settings-teams"))


class SkylightDisconnectView(LoginRequiredMixin, View):
    def post(self, request, team_pk):
        _owner_membership_or_404(request.user, team_pk)
        connection = get_object_or_404(SkylightConnection, team_id=team_pk)

        ExternalLink.objects.filter(
            provider=ExternalLink.Provider.SKYLIGHT, task__team_id=team_pk
        ).delete()
        connection.delete()

        messages.success(request, "Disconnected Skylight.")
        return redirect(reverse("users:settings-teams"))
