from __future__ import annotations

from typing import Any

import requests


class VtodoAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error {status_code}: {detail}")


class VtodoClient:
    def __init__(self, base_url: str, token: str) -> None:
        self._base = base_url.rstrip("/") + "/api/v1"
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Token {token}"})

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

    def list_tasks(self, status: str | None = None, tags: list[str] | None = None) -> list[dict]:
        params: dict[str, Any] = {}
        if status:
            params["status"] = status
        if tags:
            params["tags"] = tags
        r = self._session.get(f"{self._base}/tasks/", params=params)
        self._raise(r)
        return r.json()

    def get_task(self, task_id: int) -> dict:
        r = self._session.get(f"{self._base}/tasks/{task_id}/")
        self._raise(r)
        return r.json()

    def create_task(
        self,
        title: str,
        notes: str | None = None,
        status: str | None = None,
        due_date: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"title": title}
        if notes is not None:
            payload["notes"] = notes
        if status is not None:
            payload["status"] = status
        if due_date is not None:
            payload["due_date"] = due_date
        if tags is not None:
            payload["tags"] = tags
        r = self._session.post(f"{self._base}/tasks/", json=payload)
        self._raise(r)
        return r.json()

    def update_task(self, task_id: int, **fields: Any) -> dict:
        r = self._session.patch(f"{self._base}/tasks/{task_id}/", json=fields)
        self._raise(r)
        return r.json()

    def delete_task(self, task_id: int) -> None:
        r = self._session.delete(f"{self._base}/tasks/{task_id}/")
        self._raise(r)

    def move_task(self, task_id: int, new_status: str) -> dict:
        r = self._session.post(
            f"{self._base}/tasks/{task_id}/move/", json={"new_status": new_status}
        )
        self._raise(r)
        return r.json()

    # ── Statuses ───────────────────────────────────────────────────────────

    def list_statuses(self) -> list[dict]:
        r = self._session.get(f"{self._base}/statuses/")
        self._raise(r)
        return r.json()

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
        r = self._session.post(f"{self._base}/statuses/", json=payload)
        self._raise(r)
        return r.json()

    def update_status(self, slug: str, **fields: Any) -> dict:
        r = self._session.patch(f"{self._base}/statuses/{slug}/", json=fields)
        self._raise(r)
        return r.json()

    def delete_status(self, slug: str) -> None:
        r = self._session.delete(f"{self._base}/statuses/{slug}/")
        self._raise(r)

    # ── Comments ───────────────────────────────────────────────────────────

    def list_comments(self, task_id: int) -> list[dict]:
        r = self._session.get(f"{self._base}/tasks/{task_id}/comments/")
        self._raise(r)
        return r.json()

    def add_comment(self, task_id: int, body: str) -> dict:
        r = self._session.post(f"{self._base}/tasks/{task_id}/comments/", json={"body": body})
        self._raise(r)
        return r.json()

    def delete_comment(self, comment_id: int) -> None:
        r = self._session.delete(f"{self._base}/comments/{comment_id}/")
        self._raise(r)
