import requests
from django.utils import timezone

BASE_URL = "https://app.ourskylight.com"
REQUEST_TIMEOUT = 15


class SkylightAuthError(Exception):
    """Raised when login with the stored credentials is rejected."""


class SkylightAPIError(Exception):
    """Raised for any non-2xx response other than a retried 401, and for
    network-level failures (timeout, connection refused, DNS, ...) reaching
    Skylight at all -- callers only need to handle the two Skylight exception
    types to cover every way a request to Skylight can fail."""


def login(email: str, password: str) -> str:
    """Bare credential check against POST /api/sessions. Used both to validate
    credentials during the connect flow (before anything is saved) and by
    SkylightClient.authenticate() for a connection that already exists."""
    try:
        response = requests.post(
            f"{BASE_URL}/api/sessions",
            json={"email": email, "password": password},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        raise SkylightAPIError(f"Couldn't reach Skylight to log in: {exc}") from exc
    if response.status_code != 200:
        raise SkylightAuthError(f"Skylight login failed for {email}: {response.status_code}")
    return response.json()["data"]["attributes"]["token"]


class SkylightClient:
    """Thin wrapper around Skylight's unofficial, reverse-engineered API.

    There is no OAuth and no documented token refresh/expiry, so this client
    re-authenticates with the stored email/password whenever a call comes back 401.
    """

    def __init__(self, connection):
        self.connection = connection
        self.session = requests.Session()

    def authenticate(self) -> str:
        token = login(self.connection.email, self.connection.get_password())
        self.connection.set_token(token)
        self.connection.token_fetched_at = timezone.now()
        self.connection.save(update_fields=["token_encrypted", "token_fetched_at"])
        return token

    def _request(self, method, path, params=None, json_body=None, _retry=True):
        token = self.connection.get_token() or self.authenticate()
        try:
            response = self.session.request(
                method,
                f"{BASE_URL}{path}",
                params=params,
                json=json_body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.exceptions.RequestException as exc:
            raise SkylightAPIError(f"Couldn't reach Skylight: {method} {path}: {exc}") from exc
        if response.status_code == 401 and _retry:
            self.authenticate()
            return self._request(method, path, params=params, json_body=json_body, _retry=False)
        if response.status_code >= 400:
            raise SkylightAPIError(
                f"{method} {path} -> {response.status_code}: {response.text[:500]}"
            )
        if not response.content:
            return None
        return response.json()

    def list_source_calendars(self):
        path = f"/api/frames/{self.connection.frame_id}/source_calendars"
        return self._request("GET", path)["data"]

    def list_categories(self):
        path = f"/api/frames/{self.connection.frame_id}/categories"
        return self._request("GET", path)["data"]

    def list_calendar_events(self, date_min, date_max, timezone_name="UTC"):
        path = f"/api/frames/{self.connection.frame_id}/calendar_events"
        params = {
            "date_min": date_min,
            "date_max": date_max,
            "timezone": timezone_name,
            "include": "categories,calendar_account",
        }
        return self._request("GET", path, params=params)["data"]

    def create_calendar_event(self, payload):
        path = f"/api/frames/{self.connection.frame_id}/calendar_events"
        return self._request("POST", path, json_body=payload)["data"]

    def update_calendar_event(self, event_id, payload):
        path = f"/api/frames/{self.connection.frame_id}/calendar_events/{event_id}"
        return self._request("PUT", path, json_body=payload)["data"]

    def delete_calendar_event(self, event_id):
        path = f"/api/frames/{self.connection.frame_id}/calendar_events/{event_id}"
        self._request("DELETE", path)
