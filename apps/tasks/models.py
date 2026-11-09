from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils.text import slugify

# (name, slug, order, is_done) — the starter workflow given to every new personal
# board, so a fresh owner never faces an empty status list.
DEFAULT_STATUS_DEFS = [
    ("Backlog", "backlog", 0, False),
    ("To Do", "todo", 1, False),
    ("In Progress", "in_progress", 2, False),
    ("Done", "done", 3, True),
]


class TaskStatus(models.Model):
    # Who created the row. The workspace owns it, so it outlives this person.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_statuses",
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="statuses",
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=50)
    order = models.PositiveSmallIntegerField(default=0)
    color = models.CharField(max_length=7, blank=True, default="")
    is_done = models.BooleanField(default=False)

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "slug"],
                name="taskstatus_unique_workspace_slug",
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class TaskState(models.TextChoices):
    """Where a task is in its lifecycle. See apps/tasks/lifecycle.py."""

    OPEN = "open", "Open"
    DONE = "done", "Done"
    ARCHIVED = "archived", "Archived"


class ClaimState(models.TextChoices):
    """Where a task's lease is. See apps/tasks/claims.py."""

    UNCLAIMED = "unclaimed", "Unclaimed"
    HELD = "held", "Held"
    LAPSED = "lapsed", "Lapsed"


class TaskQuerySet(models.QuerySet):
    def in_state(self, state):
        if state == TaskState.ARCHIVED:
            return self.filter(is_archived=True)
        qs = self.filter(is_archived=False, completed_at__isnull=(state == TaskState.OPEN))
        if state == TaskState.OPEN:
            # lifecycle.py keeps completed_at in step with the status, but a
            # raw ORM write can still leave a task in a done column without
            # it. Such a task is not open.
            in_done_status = TaskStatus.objects.filter(
                workspace_id=models.OuterRef("workspace_id"),
                slug=models.OuterRef("status"),
                is_done=True,
            )
            qs = qs.exclude(models.Exists(in_done_status))
        return qs

    def open(self):
        return self.in_state(TaskState.OPEN)

    def claimable(self, now=None):
        """Tasks nobody holds: never claimed, released, or lapsed."""
        from django.utils import timezone

        now = now or timezone.now()
        return self.filter(
            models.Q(claimed_by__isnull=True)
            | models.Q(claim_expires_at__isnull=True)
            | models.Q(claim_expires_at__lte=now)
        )


class Task(models.Model):
    # Who created the row. The workspace owns it, so it outlives this person.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="tasks",
    )
    title = models.CharField(max_length=500)
    notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=50, default="todo")
    # Status slug to restore when reopening a completed task — set when a move
    # transitions the task into a done status, cleared on any move out of one.
    previous_status = models.CharField(max_length=50, blank=True, default="")
    order = models.PositiveIntegerField(default=0)
    due_date = models.DateField(null=True, blank=True)
    # Optional time-of-day for due_date, used when syncing to external calendars
    # so events get a real start time instead of always being all-day.
    due_time = models.TimeField(null=True, blank=True)
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    tags = models.JSONField(default=list, blank=True)

    is_archived = models.BooleanField(default=False)

    # Who should do it: a person in the workspace, or one of their agents.
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tasks",
    )
    # A lease: who is working on it right now, and until when. Past
    # claim_expires_at the claim has lapsed and anyone may take it. Advisory:
    # it does not stop other people editing the task.
    claimed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    claim_expires_at = models.DateTimeField(null=True, blank=True)

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
    # Set exactly while the task sits in a done status. Only
    # apps/tasks/lifecycle.py writes it.
    completed_at = models.DateTimeField(null=True, blank=True)

    objects = TaskQuerySet.as_manager()

    class Meta:
        ordering = ["order", "created_at"]

    def __str__(self):
        return self.title

    @property
    def state(self):
        if self.is_archived:
            return TaskState.ARCHIVED
        return TaskState.DONE if self.completed_at else TaskState.OPEN

    def claim_state(self, now=None):
        from django.utils import timezone

        if self.claimed_by_id is None or self.claim_expires_at is None:
            return ClaimState.UNCLAIMED
        if self.claim_expires_at <= (now or timezone.now()):
            return ClaimState.LAPSED
        return ClaimState.HELD

    def active_claim_holder_id(self, now=None):
        """Who holds an unexpired claim on this task, or None."""
        if self.claim_state(now) != ClaimState.HELD:
            return None
        return self.claimed_by_id

    def spawn_recurrence(self, completion_date):
        """Create the next recurrence of this task in backlog. Returns the new task or None.

        Also returns None when an open occurrence of this series already exists
        (same workspace, title, and schedule; not completed and not archived).
        Completing an older copy must not leave two open copies side by side.
        """
        if not self.recurrence_days:
            return None

        open_sibling = Task.objects.open().filter(
            workspace_id=self.workspace_id,
            title=self.title,
            recurrence_days=self.recurrence_days,
            recurrence_from=self.recurrence_from,
        ).exclude(pk=self.pk)
        if open_sibling.exists():
            return None

        if self.recurrence_from == self.RECURRENCE_FROM_DUE_DATE and self.due_date:
            base_date = self.due_date
        else:
            base_date = completion_date

        new_due = base_date + timedelta(days=self.recurrence_days)

        return Task.objects.create(
            user=self.user,
            workspace_id=self.workspace_id,
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
    # Null for comments written before authors were recorded.
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment on {self.task_id} @ {self.created_at}"


class TaskActivityQuerySet(models.QuerySet):
    """Blocks bulk edits and deletes so TaskActivity.objects can't rewrite the
    log. Nulling `task` is the one update allowed: it is how on_delete=SET_NULL
    is applied when a task is deleted. Deletion cascades (owner deleted) go
    through the collector, not QuerySet.delete(), so they still work."""

    def update(self, **kwargs):
        if kwargs.keys() == {"task"} and kwargs["task"] is None:
            return super().update(**kwargs)
        raise ValueError("TaskActivity is append-only.")

    def delete(self):
        raise ValueError("TaskActivity is append-only.")


class TaskActivity(models.Model):
    """Append-only history of changes to a task.

    Kept lean on purpose: one short row per changed field, values truncated to
    255 chars, and free text (notes, comment bodies) is never copied in -- the
    row only says that it changed. `user` is the task's owner, so history stays
    scoped (and is still listable) after the task itself is deleted; `task` is
    nulled on delete and `task_pk` keeps the original id.
    """

    SOURCE_WEB = "web"
    SOURCE_API = "api"
    SOURCE_MCP = "mcp"
    SOURCE_SYSTEM = "system"
    SOURCE_CHOICES = [
        (SOURCE_WEB, "Web"),
        (SOURCE_API, "API"),
        (SOURCE_MCP, "MCP"),
        (SOURCE_SYSTEM, "System"),
    ]

    CREATED = "created"
    UPDATED = "updated"
    MOVED = "moved"
    ARCHIVED = "archived"
    UNARCHIVED = "unarchived"
    DELETED = "deleted"
    COMMENTED = "commented"
    COMMENT_DELETED = "comment_deleted"
    CLAIMED = "claimed"
    RELEASED = "released"
    ACTION_CHOICES = [
        (CREATED, "Created"),
        (UPDATED, "Updated"),
        (MOVED, "Moved"),
        (ARCHIVED, "Archived"),
        (UNARCHIVED, "Unarchived"),
        (DELETED, "Deleted"),
        (COMMENTED, "Commented"),
        (COMMENT_DELETED, "Comment deleted"),
        (CLAIMED, "Claimed"),
        (RELEASED, "Released"),
    ]

    # Who created the row. The workspace owns it, so it outlives this person.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_activity",
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="activity",
    )
    task = models.ForeignKey(
        Task,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity",
    )
    task_pk = models.PositiveBigIntegerField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    source = models.CharField(max_length=8, choices=SOURCE_CHOICES)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    field = models.CharField(max_length=32, blank=True, default="")
    old_value = models.CharField(max_length=255, blank=True, default="")
    new_value = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TaskActivityQuerySet.as_manager()

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["user", "task_pk", "created_at"])]

    def __str__(self):
        return f"{self.action} {self.field} on {self.task_pk} @ {self.created_at}"

    @property
    def field_label(self):
        return self.field.replace("_", " ")

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("TaskActivity is append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("TaskActivity is append-only.")
