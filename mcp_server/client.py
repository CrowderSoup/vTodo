from __future__ import annotations

import copy
from typing import Any

import requests


class VtodoAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error {status_code}: {detail}")


class VtodoClient:
    def __init__(self, base_url: str, token: str, scheme: str = "Token") -> None:
        """scheme is "Token" for a DRF API token (stdio mode) or "Bearer" for
        a remote caller's OAuth access token forwarded by sse mode."""
        self._base = base_url.rstrip("/") + "/api/v1"
        self._session = requests.Session()
        # X-Vtodo-Client labels this traffic as MCP in the task activity log.
        self._session.headers.update({"Authorization": f"{scheme} {token}", "X-Vtodo-Client": "mcp"})
        # Sent with each request. Empty means the caller's personal workspace.
        self._headers: dict[str, str] = {}

    def in_workspace(self, workspace_id: int | None) -> "VtodoClient":
        """A client acting in another workspace, sharing this one's session.
        None keeps the personal workspace."""
        if workspace_id is None:
            return self
        scoped = copy.copy(self)
        scoped._headers = {"X-Workspace-Id": str(workspace_id)}
        return scoped

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        r = self._session.request(method, f"{self._base}{path}", headers=self._headers, **kwargs)
        self._raise(r)
        return r

    def _raise(self, response: requests.Response) -> None:
        try:
            response.raise_for_status()
        except requests.HTTPError:
            try:
                body = response.json()
                if isinstance(body, dict):
                    detail = body.get("detail") or str(body)
                else:
                    detail = str(body)
            except Exception:
                detail = response.text or response.reason
            raise VtodoAPIError(response.status_code, detail)

    # ── Tasks ──────────────────────────────────────────────────────────────

    def list_tasks(
        self,
        status: str | None = None,
        tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        assignee: str | None = None,
        claimable: bool = False,
    ) -> list[dict]:
        params: dict[str, Any] = {}
        if status:
            params["status"] = status
        if tags:
            params["tags"] = tags
        if exclude_tags:
            params["exclude_tags"] = exclude_tags
        if assignee:
            params["assignee"] = assignee
        if claimable:
            params["claimable"] = "true"
        return self._request("GET", "/tasks/", params=params).json()

    def reorder_tasks(self, order: list[int]) -> None:
        self._request("POST", "/tasks/reorder/", json={"order": order})

    def get_task(self, task_id: int) -> dict:
        return self._request("GET", f"/tasks/{task_id}/").json()

    def create_task(
        self,
        title: str,
        notes: str | None = None,
        status: str | None = None,
        due_date: str | None = None,
        due_time: str | None = None,
        duration_minutes: int | None = None,
        tags: list[str] | None = None,
        recurrence_days: int | None = None,
        recurrence_from: str | None = None,
        assignee: int | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"title": title}
        if notes is not None:
            payload["notes"] = notes
        if status is not None:
            payload["status"] = status
        if due_date is not None:
            payload["due_date"] = due_date
        if due_time is not None:
            payload["due_time"] = due_time
        if duration_minutes is not None:
            payload["duration_minutes"] = duration_minutes
        if tags is not None:
            payload["tags"] = tags
        if recurrence_days is not None:
            payload["recurrence_days"] = recurrence_days
        if recurrence_from is not None:
            payload["recurrence_from"] = recurrence_from
        if assignee is not None:
            payload["assignee"] = assignee
        return self._request("POST", "/tasks/", json=payload).json()

    def update_task(self, task_id: int, **fields: Any) -> dict:
        return self._request("PATCH", f"/tasks/{task_id}/", json=fields).json()

    def delete_task(self, task_id: int) -> None:
        self._request("DELETE", f"/tasks/{task_id}/")

    def claim_task(self, task_id: int, lease_seconds: int | None = None) -> dict:
        payload = {} if lease_seconds is None else {"lease_seconds": lease_seconds}
        return self._request("POST", f"/tasks/{task_id}/claim/", json=payload).json()

    def release_task(self, task_id: int) -> dict:
        return self._request("POST", f"/tasks/{task_id}/release/").json()

    def claim_next_task(self, lease_seconds: int | None = None) -> dict | None:
        """The claimed task, or None when nothing assigned is waiting."""
        payload = {} if lease_seconds is None else {"lease_seconds": lease_seconds}
        r = self._request("POST", "/tasks/claim-next/", json=payload)
        return None if r.status_code == 204 else r.json()

    def move_task(self, task_id: int, new_status: str) -> dict:
        return self._request("POST", f"/tasks/{task_id}/move/", json={"new_status": new_status}).json()

    def export_tasks(self) -> str:
        """The workspace's tasks as an iCalendar (.ics) document."""
        return self._request("GET", "/tasks/export/").text

    # ── Statuses ───────────────────────────────────────────────────────────

    def list_statuses(self) -> list[dict]:
        return self._request("GET", "/statuses/").json()

    def create_status(
        self,
        name: str,
        color: str | None = None,
        is_done: bool | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"name": name}
        if color is not None:
            payload["color"] = color
        if is_done is not None:
            payload["is_done"] = is_done
        return self._request("POST", "/statuses/", json=payload).json()

    def update_status(self, slug: str, **fields: Any) -> dict:
        return self._request("PATCH", f"/statuses/{slug}/", json=fields).json()

    def delete_status(self, slug: str) -> None:
        self._request("DELETE", f"/statuses/{slug}/")

    def reorder_statuses(self, order: list[int]) -> None:
        self._request("POST", "/statuses/reorder/", json={"order": order})

    # ── Comments ───────────────────────────────────────────────────────────

    def list_comments(self, task_id: int) -> list[dict]:
        return self._request("GET", f"/tasks/{task_id}/comments/").json()

    def add_comment(self, task_id: int, body: str) -> dict:
        return self._request("POST", f"/tasks/{task_id}/comments/", json={"body": body}).json()

    def delete_comment(self, comment_id: int) -> None:
        self._request("DELETE", f"/comments/{comment_id}/")

    # ── Activity ───────────────────────────────────────────────────────────

    def list_activity(self, task_id: int) -> list[dict]:
        return self._request("GET", f"/tasks/{task_id}/activity/").json()

    # ── Workspaces ─────────────────────────────────────────────────────────

    def list_workspaces(self) -> list[dict]:
        return self._request("GET", "/workspaces/").json()

    def list_assignees(self) -> list[dict]:
        return self._request("GET", "/assignees/").json()
