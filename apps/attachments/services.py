"""Attaching files to tasks, through vUpload.

Callers check permission first (`ensure_can_write` / `require_write_on`):
these functions only make sure a file id belongs to the task's workspace.

The upload itself is two steps, so bytes go straight from the device to the
bucket: `start_upload` returns a signed PUT URL, the device PUTs the file, and
`finish_upload` asks vUpload to check it and records the attachment.
`upload_bytes` does all three for callers that already hold the bytes (the
API's multipart upload, MCP's base64 fallback).
"""

import requests
from django.db import transaction

from apps.attachments import vupload
from apps.attachments.models import Attachment, PendingDeletion
from apps.tasks import activity
from apps.tasks.models import TaskActivity

MAX_BYTES = 25 * 1024 * 1024
# What vTodo's vUpload app allows (`--preset vtodo`). vUpload enforces it and
# checks the bytes; this list is for file pickers and early, friendly errors.
ALLOWED_TYPES = {
    "image/jpeg": ".jpg,.jpeg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/markdown": ".md,.markdown",
    "text/csv": ".csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/vnd.oasis.opendocument.presentation": ".odp",
}
EXTENSION_TYPES = {
    ext: ctype for ctype, exts in ALLOWED_TYPES.items() for ext in exts.split(",")
}
ACCEPT = ",".join(list(ALLOWED_TYPES) + list(EXTENSION_TYPES))


class AttachmentError(Exception):
    """Something the person can fix or should know. `message` is safe to show."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def enabled():
    return vupload.get_client() is not None


def _client():
    client = vupload.get_client()
    if client is None:
        raise AttachmentError("Attachments aren't available right now.", status=503)
    return client


def owner_for(workspace_id):
    return f"workspace:{workspace_id}"


def guess_type(filename, declared=""):
    """The declared type if vTodo allows it, else one from the extension.

    Browsers report "" or application/octet-stream for .md, .heic and
    others. vUpload checks the bytes either way, so a wrong guess fails there.
    """
    declared = (declared or "").split(";")[0].strip().lower()
    if declared in ALLOWED_TYPES:
        return declared
    name = (filename or "").lower()
    dot = name.rfind(".")
    return EXTENSION_TYPES.get(name[dot:], declared) if dot >= 0 else declared


def _check_declared(filename, content_type, size):
    if not filename or not filename.strip():
        raise AttachmentError("The file needs a name.")
    if content_type not in ALLOWED_TYPES:
        raise AttachmentError(
            "That kind of file can't be attached. Images, PDFs, text, and "
            "Office or OpenDocument files work.",
            status=415,
        )
    if size is None or size < 0:
        raise AttachmentError("The file size is missing.")
    if size > MAX_BYTES:
        raise AttachmentError("Files can be up to 25 MB.", status=413)


_VUPLOAD_MESSAGES = {
    "file_too_large": ("Files can be up to 25 MB.", 413),
    "unsupported_type": ("That kind of file can't be attached.", 415),
    "quota_exceeded": ("This workspace is out of attachment storage (1 GB).", 409),
    "upload_missing": ("The file hasn't finished uploading. Try again.", 409),
    "upload_rejected": ("The file isn't what its name says it is, so it wasn't attached.", 422),
    "not_found": ("That upload wasn't found. It may have expired; try again.", 404),
}


def _translate(err):
    message, status = _VUPLOAD_MESSAGES.get(
        err.code, ("Attachments aren't available right now. Try again in a moment.", 503)
    )
    return AttachmentError(message, status=status)


def start_upload(*, task, filename, content_type, size):
    """Reserve space and return where the device should PUT the bytes:
    {file_id, upload_url, upload_method, upload_headers, expires_at}."""
    content_type = guess_type(filename, content_type)
    _check_declared(filename, content_type, size)
    try:
        resp = _client().create_upload(
            owner=owner_for(task.workspace_id),
            filename=filename,
            content_type=content_type,
            size=size,
        )
    except vupload.VUploadError as err:
        raise _translate(err) from err
    return {
        "file_id": resp["file"]["id"],
        "upload_url": resp["upload_url"],
        "upload_method": resp["upload_method"],
        "upload_headers": resp["upload_headers"],
        "expires_at": resp["expires_at"],
    }


def finish_upload(*, task, file_id, actor, source, comment=None):
    """Have vUpload check the uploaded bytes, then record the attachment.

    Finishing the same upload twice returns the attachment from the first time.
    """
    file_id = str(file_id)
    if comment is not None and comment.task_id != task.pk:
        raise AttachmentError("That comment isn't on this task.")
    existing = Attachment.objects.filter(file_id=file_id).first()
    if existing is not None:
        if existing.task_id != task.pk:
            raise AttachmentError("That upload wasn't found.", status=404)
        return existing

    client = _client()
    try:
        info = client.get_file(file_id)
        # vUpload only knows the file belongs to vTodo. That it belongs to this
        # workspace is vTodo's check, so one workspace can't claim another's upload.
        if info["owner"] != owner_for(task.workspace_id):
            raise AttachmentError("That upload wasn't found.", status=404)
        info = client.complete(file_id)
    except vupload.VUploadError as err:
        raise _translate(err) from err

    with transaction.atomic():
        attachment, created = Attachment.objects.get_or_create(
            file_id=file_id,
            defaults={
                "workspace_id": task.workspace_id,
                "task": task,
                "comment": comment,
                "uploaded_by": actor if getattr(actor, "pk", None) else None,
                "original_name": info["filename"],
                "content_type": info["content_type"],
                "size": info["size"],
            },
        )
        if created:
            activity.record(
                task, TaskActivity.ATTACHED, actor=actor, source=source, new=attachment.original_name
            )
    return attachment


def upload_bytes(*, task, filename, content_type, data, actor, source, comment=None):
    """Upload bytes vTodo already holds, then finish. Used by the API and MCP."""
    upload = start_upload(task=task, filename=filename, content_type=content_type, size=len(data))
    try:
        resp = requests.put(
            upload["upload_url"], data=data, headers=upload["upload_headers"], timeout=60
        )
    except requests.RequestException as exc:
        raise AttachmentError("The upload failed. Try again.", status=503) from exc
    if resp.status_code >= 300:
        raise AttachmentError("The upload failed. Try again.", status=503)
    return finish_upload(task=task, file_id=upload["file_id"], actor=actor, source=source, comment=comment)


def download_url(attachment, *, inline=False):
    """A link to the file that works for 5 minutes. Only raster images are
    ever inline; vUpload enforces that too."""
    try:
        return _client().download_url(attachment.file_id, inline=inline and attachment.is_image)
    except vupload.VUploadError as err:
        raise _translate(err) from err


def can_delete(membership, attachment, user):
    """The uploader, while they can still write, or a workspace owner."""
    if membership is None or not membership.can_write():
        return False
    return membership.can_admin() or (
        attachment.uploaded_by_id is not None and attachment.uploaded_by_id == user.pk
    )


def delete_attachment(attachment, *, actor, source):
    """Delete the row. The signal queues the vUpload delete in this transaction."""
    with transaction.atomic():
        activity.record(
            attachment.task,
            TaskActivity.ATTACHMENT_DELETED,
            actor=actor,
            source=source,
            old=attachment.original_name,
        )
        attachment.delete()


def process_pending_deletions(limit=200):
    """Send queued deletes to vUpload. Returns how many were confirmed.

    Rows are locked with SKIP LOCKED, so the post-commit hook and the beat
    task can run at once without sending the same delete twice.
    """
    client = vupload.get_client()
    if client is None:
        return 0
    done = 0
    with transaction.atomic():
        rows = list(PendingDeletion.objects.select_for_update(skip_locked=True).order_by("pk")[:limit])
        for row in rows:
            try:
                if row.kind == PendingDeletion.KIND_OWNER:
                    client.delete_owner(row.target)
                else:
                    client.delete_file(row.target)
            except vupload.VUploadError as err:
                row.attempts += 1
                row.last_error = str(err)[:255]
                row.save(update_fields=["attempts", "last_error"])
                if err.status == 0:
                    break  # vUpload is down; the beat task retries
                continue
            row.delete()
            done += 1
    return done
