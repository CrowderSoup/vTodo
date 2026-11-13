"""An in-memory vUpload for tests. It follows the API in vUpload's API.md:
owners, a per-owner limit, pending → ready on complete, and a rejected upload
deleted on complete. Use the `fake_vupload` fixture (root conftest.py)."""

import uuid

from apps.attachments.vupload import VUploadError


class FakeVUpload:
    def __init__(self, owner_limit=1024 * 1024 * 1024):
        self.files = {}  # id -> dict
        self.objects = {}  # id -> (bytes, content_type), what the device PUT
        self.owner_limit = owner_limit
        self.deleted_owners = []
        self.down = False

    # What a device does with the signed URL.
    def put(self, file_id, data, content_type=None):
        f = self.files[str(file_id)]
        self.objects[str(file_id)] = (data, content_type or f["content_type"])

    def _check(self):
        if self.down:
            raise VUploadError(0, "unreachable", "connection refused")

    def _file(self, file_id):
        f = self.files.get(str(file_id))
        if f is None:
            raise VUploadError(404, "not_found", "no such file")
        return f

    def create_upload(self, *, owner, filename, content_type, size):
        self._check()
        used = sum(f["size"] for f in self.files.values() if f["owner"] == owner)
        if used + size > self.owner_limit:
            raise VUploadError(409, "quota_exceeded", "limit")
        fid = str(uuid.uuid4())
        self.files[fid] = {
            "id": fid, "owner": owner, "filename": filename, "content_type": content_type,
            "size": size, "status": "pending",
        }
        return {
            "file": dict(self.files[fid]),
            "upload_url": f"https://bucket.test/vtodo/{fid}?sig=1",
            "upload_method": "PUT",
            "upload_headers": {"Content-Type": content_type},
            "expires_at": "2026-11-13T18:15:00Z",
        }

    def get_file(self, file_id):
        self._check()
        return dict(self._file(file_id))

    def complete(self, file_id):
        self._check()
        f = self._file(file_id)
        if f["status"] == "ready":
            return dict(f)
        obj = self.objects.get(f["id"])
        if obj is None:
            raise VUploadError(409, "upload_missing", "nothing uploaded")
        data, ctype = obj
        if len(data) != f["size"] or ctype != f["content_type"] or data.startswith(b"MZ"):
            del self.files[f["id"]]
            del self.objects[f["id"]]
            raise VUploadError(422, "upload_rejected", "mismatch")
        f["status"] = "ready"
        return dict(f)

    def download_url(self, file_id, *, inline=False):
        self._check()
        f = self._file(file_id)
        if f["status"] != "ready":
            raise VUploadError(409, "not_ready", "pending")
        return f"https://bucket.test/vtodo/{file_id}?get=1&disposition={'inline' if inline else 'attachment'}"

    def delete_file(self, file_id):
        self._check()
        self.files.pop(str(file_id), None)
        self.objects.pop(str(file_id), None)

    def delete_owner(self, owner):
        self._check()
        ids = [i for i, f in self.files.items() if f["owner"] == owner]
        for i in ids:
            self.delete_file(i)
        self.deleted_owners.append(owner)
        return len(ids)

    def usage(self, owner):
        self._check()
        files = [f for f in self.files.values() if f["owner"] == owner]
        return {
            "bytes": sum(f["size"] for f in files),
            "files": sum(1 for f in files if f["status"] == "ready"),
            "limit_bytes": self.owner_limit,
        }
