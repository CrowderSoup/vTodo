"""A small client for vUpload, the suite's internal file store.

vUpload has no public hostname. It answers on the droplet's Docker network at
VUPLOAD_URL (http://vupload:8080) and authenticates vTodo with VUPLOAD_APP_KEY.
Its API is documented in the vUpload repo's API.md. When either setting is
empty, `get_client()` returns None and attachments are switched off.
"""

import requests
from django.conf import settings


class VUploadError(Exception):
    """vUpload answered with an error, or couldn't be reached (status 0)."""

    def __init__(self, status, code, message):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


class Client:
    def __init__(self, base_url, key, timeout=5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {key}"

    def _call(self, method, path, json=None, params=None, ok_statuses=()):
        url = self.base_url + path
        # vUpload is restarted in place on deploy (no proxy), so a refused
        # connection gets one retry.
        for attempt in (1, 2):
            try:
                resp = self.session.request(method, url, json=json, params=params, timeout=self.timeout)
                break
            except requests.ConnectionError as exc:
                if attempt == 2:
                    raise VUploadError(0, "unreachable", str(exc)) from exc
            except requests.RequestException as exc:
                raise VUploadError(0, "unreachable", str(exc)) from exc
        if resp.status_code in ok_statuses:
            return None
        if resp.status_code >= 400:
            try:
                err = resp.json()["error"]
                code, message = err["code"], err["message"]
            except (ValueError, KeyError, TypeError):
                code, message = "error", resp.text[:200]
            raise VUploadError(resp.status_code, code, message)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def create_upload(self, *, owner, filename, content_type, size):
        return self._call(
            "POST",
            "/v1/uploads",
            json={"owner": owner, "filename": filename, "content_type": content_type, "size": size},
        )

    def complete(self, file_id):
        return self._call("POST", f"/v1/files/{file_id}/complete")

    def get_file(self, file_id):
        return self._call("GET", f"/v1/files/{file_id}")

    def download_url(self, file_id, *, inline=False):
        params = {"disposition": "inline" if inline else "attachment"}
        return self._call("GET", f"/v1/files/{file_id}/url", params=params)["url"]

    def delete_file(self, file_id):
        # Already gone is fine: the outbox may retry a delete that landed.
        self._call("DELETE", f"/v1/files/{file_id}", ok_statuses=(404,))

    def delete_owner(self, owner):
        return self._call("DELETE", f"/v1/owners/{owner}")["deleted"]

    def usage(self, owner):
        return self._call("GET", f"/v1/owners/{owner}/usage")


def get_client():
    url = getattr(settings, "VUPLOAD_URL", "")
    key = getattr(settings, "VUPLOAD_APP_KEY", "")
    if not url or not key:
        return None
    return Client(url, key)
