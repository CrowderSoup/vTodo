from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils.text import slugify

# (name, slug, order, is_done) — the starter workflow given to every new personal
# board and every new team, so a fresh owner never faces an empty status list.
DEFAULT_STATUS_DEFS = [
    ("Backlog", "backlog", 0, False),
    ("To Do", "todo", 1, False),
    ("In Progress", "in_progress", 2, False),
    ("Done", "done", 3, True),
]


class TaskStatus(models.Model):
    """Owned by exactly one of user (personal) or team (shared team workflow)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="task_statuses",
        null=True,
        blank=True,
    )
    team = models.ForeignKey(
        "teams.Team",
        on_delete=models.CASCADE,
        related_name="task_statuses",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=50)
    order = models.PositiveSmallIntegerField(default=0)
    color = models.CharField(max_length=7, blank=True, default="")
    is_done = models.BooleanField(default=False)

    class Meta:
        ordering = ["order"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(user__isnull=False, team__isnull=True)
                    | models.Q(user__isnull=True, team__isnull=False)
                ),
                name="taskstatus_exactly_one_owner",
            ),
            models.UniqueConstraint(
                fields=["user", "slug"],
                condition=models.Q(team__isnull=True),
                name="taskstatus_unique_user_slug",
            ),
            models.UniqueConstraint(
                fields=["team", "slug"],
                condition=models.Q(user__isnull=True),
                name="taskstatus_unique_team_slug",
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Task(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tasks",
    )
    team = models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tasks",
    )
    title = models.CharField(max_length=500)
    notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=50, default="todo")
    # Status slug to restore when reopening a completed task — set when a move
    # transitions the task into a done status, cleared on any move out of one.
    previous_status = models.CharField(max_length=50, blank=True, default="")
    order = models.PositiveIntegerField(default=0)
    due_date = models.DateField(null=True, blank=True)
    # Optional time-of-day for due_date, used when syncing to external calendars (e.g.
    # Skylight) so events get a real start time instead of always being all-day.
    due_time = models.TimeField(null=True, blank=True)
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    tags = models.JSONField(default=list, blank=True)

    is_archived = models.BooleanField(default=False)

    RECURRENCE_FROM_COMPLETION = "completion"
    RECURRENCE_FROM_DUE_DATE = "due_date"
    RECURRENCE_FROM_CHOICES = [
        (RECURRENCE_FROM_COMPLETION, "Completion date"),
        (RECURRENCE_FROM_DUE_DATE, "Due date"),
    ]
    recurrence_days = models.PositiveSmallIntegerField(null=True, blank=True)
    recurrence_from = models.CharField(
        max_length=10,
        choices=RECURRENCE_FROM_CHOICES,
        default=RECURRENCE_FROM_COMPLETION,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["order", "created_at"]

    def __str__(self):
        return self.title

    def spawn_recurrence(self, completion_date):
        """Create the next recurrence of this task in backlog. Returns the new task or None."""
        if not self.recurrence_days:
            return None

        if self.recurrence_from == self.RECURRENCE_FROM_DUE_DATE and self.due_date:
            base_date = self.due_date
        else:
            base_date = completion_date

        new_due = base_date + timedelta(days=self.recurrence_days)

        return Task.objects.create(
            user=self.user,
            team=self.team,
            title=self.title,
            notes=self.notes,
            status="backlog",
            due_date=new_due,
            due_time=self.due_time,
            duration_minutes=self.duration_minutes,
            tags=list(self.tags),
            recurrence_days=self.recurrence_days,
            recurrence_from=self.recurrence_from,
        )


class TaskComment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment on {self.task_id} @ {self.created_at}"


class TaskActivity(models.Model):
    """Audit trail entry for a field change on a task (e.g. assignee)."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="activity")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="task_activity_entries",
    )
    field = models.CharField(max_length=50)
    old_value = models.CharField(max_length=255, blank=True, default="")
    new_value = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name_plural = "task activity"

    def __str__(self):
        return f"{self.field} change on {self.task_id} @ {self.created_at}"
