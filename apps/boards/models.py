from django.conf import settings
from django.db import models


class Board(models.Model):
    """One board per workspace. `user` is who created it, if they still exist."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="boards",
    )
    workspace = models.OneToOneField(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="board",
    )
    name = models.CharField(max_length=255, default="My Board")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.user})"


class Column(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="columns")
    label = models.CharField(max_length=100)
    # filter_config schema: {"statuses": [...], "tags": [...], "due": null|"overdue"|"today"|"this_week"}
    filter_config = models.JSONField(default=dict)
    order = models.PositiveSmallIntegerField(default=0)
    color = models.CharField(max_length=7, blank=True, default="")

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.label} ({self.board})"

    def default_status(self, user=None):
        """Returns the status slug to assign to tasks added in this column."""
        statuses = self.filter_config.get("statuses", [])
        if statuses:
            return statuses[0]
        from apps.tasks.models import TaskStatus

        first = TaskStatus.objects.filter(workspace_id=self.board.workspace_id).first()
        return first.slug if first else "todo"


class SavedFilter(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="saved_filters")
    name = models.CharField(max_length=255)
    filter_config = models.JSONField(default=dict)
    # schema: {"tags": [...], "exclude_tags": [...], "due": "...", "hidden_lanes": ["status:<pk>"|"column:<pk>", ...]}
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("board", "name")]

    def __str__(self):
        return f"{self.name} ({self.board})"
