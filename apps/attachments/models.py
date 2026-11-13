"""Files attached to tasks and comments.

The bytes live in vUpload (an internal service; see apps/attachments/vupload.py).
vTodo keeps the row that says which task a file belongs to, and decides who
may see it. vUpload's owner for every file is the workspace
(`workspace:<id>`), so files stay with the workspace when a member leaves.
"""

from django.conf import settings
from django.db import models

# Raster images a browser can show. Everything else downloads.
INLINE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


class Attachment(models.Model):
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="attachments"
    )
    # A comment attachment sets both, so "every file on this task" is one query.
    task = models.ForeignKey("tasks.Task", on_delete=models.CASCADE, related_name="attachments")
    comment = models.ForeignKey(
        "tasks.TaskComment",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # vUpload's id for the file. The object key is derived from it, never
    # from the name.
    file_id = models.UUIDField(unique=True)
    # As vUpload recorded it (control characters dropped, slashes replaced).
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=127)
    size = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["task", "created_at"])]

    def __str__(self):
        return self.original_name

    @property
    def is_image(self):
        return self.content_type in INLINE_TYPES


class PendingDeletion(models.Model):
    """An outbox for deletes in vUpload.

    Written in the same transaction that deletes the attachment (or the
    workspace), so a crash or a vUpload outage can't leave bytes behind that
    nothing points at. Tried right after commit, then retried by the
    `purge-vupload-deletions` beat task until vUpload confirms.
    """

    KIND_FILE = "file"
    KIND_OWNER = "owner"
    KIND_CHOICES = [(KIND_FILE, "File"), (KIND_OWNER, "Owner")]

    kind = models.CharField(max_length=8, choices=KIND_CHOICES)
    # A vUpload file id, or an owner such as "workspace:12".
    target = models.CharField(max_length=200)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"delete {self.kind} {self.target}"
