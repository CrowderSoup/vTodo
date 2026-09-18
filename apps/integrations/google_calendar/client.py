import requests
from django.conf import settings

TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"
REQUEST_TIMEOUT = 15


class GoogleCalendarAuthError(Exception):
    """Raised when Google rejects the stored refresh token outright (revoked,
    expired, or the user removed vtodo's access from their Google account) --
    retrying with the same token is futile."""


class GoogleCalendarAPIError(Exception):
    """Raised for any other non-2xx response, and for network-level failures
    (timeout, connection refused, DNS, ...) reaching Google at all."""


def exchange_code(code: str, redirect_uri: str) -> dict:
    """Exchanges a fresh OAuth authorization code for an access/refresh token pair.
    Used once, right after the user completes Google's consent screen."""
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        raise GoogleCalendarAPIError(f"Couldn't reach Google to exchange the auth code: {exc}") from exc
    if response.status_code != 200:
        raise GoogleCalendarAPIError(
            f"Google rejected the auth code: {response.status_code}: {response.text[:300]}"
        )
    return response.json()


def _refresh_access_token(refresh_token: str) -> str:
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        raise GoogleCalendarAPIError(f"Couldn't reach Google to refresh the access token: {exc}") from exc
    if response.status_code == 400:
        # invalid_grant is Google's code for "this refresh token no longer works."
        raise GoogleCalendarAuthError(
            f"Google rejected the refresh token: {response.status_code}: {response.text[:300]}"
        )
    if response.status_code != 200:
        raise GoogleCalendarAPIError(
            f"Google refresh_token request failed: {response.status_code}: {response.text[:300]}"
        )
    return response.json()["access_token"]


def revoke(refresh_token: str) -> None:
    """Best-effort: tells Google to invalidate the refresh token. Failures are
    swallowed by the caller -- vtodo deletes its own connection record either way."""
    requests.post(REVOKE_URL, data={"token": refresh_token}, timeout=REQUEST_TIMEOUT)


class GoogleCalendarClient:
    """Thin wrapper around the Google Calendar API v3, scoped to one user's
    dedicated "vTodo" calendar. Mints a fresh access token per call rather than
    caching one, since sync runs are infrequent and access tokens are cheap."""

    def __init__(self, connection):
        self.connection = connection
        self.session = requests.Session()

    def _request(self, method, path, params=None, json_body=None):
        access_token = _refresh_access_token(self.connection.get_refresh_token())
        try:
            response = self.session.request(
                method,
                f"{CALENDAR_API_BASE}{path}",
                params=params,
                json=json_body,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.exceptions.RequestException as exc:
            raise GoogleCalendarAPIError(f"Couldn't reach Google Calendar: {method} {path}: {exc}") from exc
        if response.status_code >= 400:
            raise GoogleCalendarAPIError(
                f"{method} {path} -> {response.status_code}: {response.text[:500]}"
            )
        if not response.content:
            return None
        return response.json()

    def create_calendar(self, summary: str) -> str:
        calendar = self._request("POST", "/calendars", json_body={"summary": summary})
        return calendar["id"]

    def delete_calendar(self, calendar_id: str) -> None:
        self._request("DELETE", f"/calendars/{calendar_id}")

    def create_event(self, calendar_id: str, payload: dict) -> dict:
        return self._request("POST", f"/calendars/{calendar_id}/events", json_body=payload)

    def update_event(self, calendar_id: str, event_id: str, payload: dict) -> dict:
        return self._request("PUT", f"/calendars/{calendar_id}/events/{event_id}", json_body=payload)

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        self._request("DELETE", f"/calendars/{calendar_id}/events/{event_id}")
