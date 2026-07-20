import uuid

import requests
from django.utils import timezone

BASE_URL = "https://app.ourskylight.com"
REQUEST_TIMEOUT = 15

# Skylight's API is unofficial/reverse-engineered and versioned via this header;
# omitting it (or sending an unrecognized client) gets silently downgraded to a
# stale default version that's since been sunset, which shows up as a 401 on
# every request -- including login -- even with correct credentials.
API_HEADERS = {
    "User-Agent": "SkylightMobile (web)",
    "Accept": "application/json",
    "Skylight-Api-Version": "2026-05-01",
}


class SkylightAuthError(Exception):
    """Raised when login with the stored credentials is rejected."""


class SkylightAPIError(Exception):
    """Raised for any non-2xx response other than a retried 401, and for
    network-level failures (timeout, connection refused, DNS, ...) reaching
    Skylight at all -- callers only need to handle the two Skylight exception
    types to cover every way a request to Skylight can fail."""


TOKEN_URL = f"{BASE_URL}/oauth/token"
CLIENT_ID = "skylight-mobile"


def refresh(refresh_token: str) -> dict:
    """Exchange a refresh_token for a fresh (access_token, refresh_token) pair via
    Skylight's OAuth token endpoint. Skylight rotates the refresh_token on every
    use -- the old one is invalidated, so callers must persist the new one every
    time this succeeds, not just the access_token.

    /api/sessions (plain email+password login) is permanently retired by
    Skylight; this OAuth grant is the only remaining way to mint tokens without
    an interactive browser login."""
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "scope": "everything",
                "refresh_token": refresh_token,
                "skylight_api_client_device_fingerprint": str(uuid.uuid4()),
                "skylight_api_client_device_platform": "web",
                "skylight_api_client_device_name": "unknown",
                "skylight_api_client_device_os_version": "10.15",
                "skylight_api_client_device_app_version": "unknown",
                "skylight_api_client_device_hardware": "Macintosh",
                "source": "js-mobile",
            },
            headers=API_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        raise SkylightAPIError(f"Couldn't reach Skylight to refresh token: {exc}") from exc
    if response.status_code != 200:
        raise SkylightAuthError(
            f"Skylight rejected the refresh token: {response.status_code}: {response.text[:300]}"
        )
    data = response.json()
    return {"access_token": data["access_token"], "refresh_token": data["refresh_token"]}


class SkylightClient:
    """Thin wrapper around Skylight's unofficial, reverse-engineered API.

    Skylight's login is OAuth2, but the only grant type usable without an
    interactive browser popup is refresh_token -- so this client re-authenticates
    via the stored (rotating) refresh token whenever a call comes back 401.
    """

    def __init__(self, connection):
        self.connection = connection
        self.session = requests.Session()

    def authenticate(self) -> str:
        result = refresh(self.connection.get_refresh_token())
        self.connection.set_token(result["access_token"])
        self.connection.set_refresh_token(result["refresh_token"])
        self.connection.token_fetched_at = timezone.now()
        self.connection.save(
            update_fields=["token_encrypted", "refresh_token_encrypted", "token_fetched_at"]
        )
        return result["access_token"]

    def _request(self, method, path, params=None, json_body=None, _retry=True):
        token = self.connection.get_token() or self.authenticate()
        try:
            response = self.session.request(
                method,
                f"{BASE_URL}{path}",
                params=params,
                json=json_body,
                headers={**API_HEADERS, "Authorization": f"Bearer {token}"},
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
