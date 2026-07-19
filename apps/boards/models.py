from django.conf import settings
from django.db import models


class Board(models.Model):
    """Owned by exactly one of user (personal board) or team (shared team board)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="boards",
        null=True,
        blank=True,
    )
    team = models.ForeignKey(
        "teams.Team",
        on_delete=models.CASCADE,
        related_name="boards",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255, default="My Board")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(user__isnull=False, team__isnull=True)
                    | models.Q(user__isnull=True, team__isnull=False)
                ),
                name="board_exactly_one_owner",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(team__isnull=True),
                name="board_unique_user",
            ),
            models.UniqueConstraint(
                fields=["team"],
                condition=models.Q(user__isnull=True),
                name="board_unique_team",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.user or self.team})"


class Column(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="columns")
    label = models.CharField(max_length=100)
    # filter_config schema: {"statuses": [...], "tags": [...], "due": null|"overdue"|"today"|"this_week",
    #                         "assignee": "any"|"me"|"unassigned"|"<user_id>" (default "any")}
    # Scope (personal vs a specific team) is determined by which Board a Column belongs to,
    # not by anything in filter_config.
    filter_config = models.JSONField(default=dict)
    order = models.PositiveSmallIntegerField(default=0)
    color = models.CharField(max_length=7, blank=True, default="")

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.label} ({self.board})"

    def default_status(self, user, team=None):
        """Returns the status slug to assign to tasks added in this column."""
        statuses = self.filter_config.get("statuses", [])
        if statuses:
            return statuses[0]
        from apps.tasks.selectors import visible_statuses_qs
        first = visible_statuses_qs(user, team=team).first()
        return first.slug if first else "todo"


class SavedFilter(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="saved_filters")
    name = models.CharField(max_length=255)
    filter_config = models.JSONField(default=dict)
    # schema: {"tags": [...], "exclude_tags": [...], "due": "...", "hidden_columns": [...]}
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("board", "name")]

    def __str__(self):
        return f"{self.name} ({self.board})"
