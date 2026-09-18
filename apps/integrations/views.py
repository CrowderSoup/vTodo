import secrets
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse
from django.views import View

from apps.integrations.google_calendar.client import GoogleCalendarAPIError, GoogleCalendarClient, exchange_code, revoke
from apps.integrations.google_calendar.sync import owned_or_assigned_tasks_qs
from apps.integrations.models import ExternalLink, GoogleCalendarConnection

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
STATE_SESSION_KEY = "google_calendar_oauth_state"


def _callback_url(request):
    return request.build_absolute_uri(reverse("integrations:google-calendar-callback"))


class GoogleCalendarConnectView(LoginRequiredMixin, View):
    """Starts a separate, incremental-consent OAuth flow for calendar access --
    distinct from the profile/email scope requested at login (allauth doesn't
    persist tokens at all, see SOCIALACCOUNT_PROVIDERS/STORE_TOKENS)."""

    def get(self, request):
        state = secrets.token_urlsafe(32)
        request.session[STATE_SESSION_KEY] = state
        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": _callback_url(request),
            "response_type": "code",
            "scope": CALENDAR_SCOPE,
            "access_type": "offline",
            "prompt": "consent",  # force a refresh_token even on a re-connect
            "state": state,
        }
        return redirect(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


class GoogleCalendarCallbackView(LoginRequiredMixin, View):
    def get(self, request):
        expected_state = request.session.pop(STATE_SESSION_KEY, None)
        state = request.GET.get("state")
        code = request.GET.get("code")
        if not code or not state or state != expected_state:
            messages.error(request, "Google Calendar connection failed. Please try again.")
            return redirect(reverse("users:settings-calendar"))

        try:
            token_data = exchange_code(code, _callback_url(request))
            refresh_token = token_data.get("refresh_token")
            if not refresh_token:
                messages.error(
                    request,
                    "Google didn't return a refresh token. Remove vtodo's access under "
                    "myaccount.google.com/permissions and try connecting again.",
                )
                return redirect(reverse("users:settings-calendar"))

            connection, _ = GoogleCalendarConnection.objects.get_or_create(
                user=request.user, defaults={"calendar_id": ""}
            )
            connection.set_refresh_token(refresh_token)
            connection.is_active = True
            connection.last_sync_error = ""
            connection.save(update_fields=["refresh_token_encrypted", "is_active", "last_sync_error"])

            client = GoogleCalendarClient(connection)
            connection.calendar_id = client.create_calendar("vTodo")
            connection.save(update_fields=["calendar_id"])
        except GoogleCalendarAPIError:
            messages.error(request, "Couldn't connect to Google Calendar. Please try again.")
            return redirect(reverse("users:settings-calendar"))

        messages.success(request, "Connected Google Calendar.")
        return redirect(reverse("users:settings-calendar"))


class GoogleCalendarDisconnectView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            connection = request.user.google_calendar_connection
        except GoogleCalendarConnection.DoesNotExist:
            return redirect(reverse("users:settings-calendar"))

        try:
            GoogleCalendarClient(connection).delete_calendar(connection.calendar_id)
        except GoogleCalendarAPIError:
            pass  # best-effort -- vtodo's own records are removed regardless
        try:
            revoke(connection.get_refresh_token())
        except Exception:
            pass  # best-effort -- vtodo's own records are removed regardless

        ExternalLink.objects.filter(
            provider=ExternalLink.Provider.GOOGLE_CALENDAR,
            task__in=owned_or_assigned_tasks_qs(request.user),
        ).delete()
        connection.delete()

        messages.success(request, "Disconnected Google Calendar.")
        return redirect(reverse("users:settings-calendar"))
