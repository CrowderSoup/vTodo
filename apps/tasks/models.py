from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils.text import slugify


class TaskStatus(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="task_statuses",
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=50)
    order = models.PositiveSmallIntegerField(default=0)
    color = models.CharField(max_length=7, blank=True, default="")
    is_done = models.BooleanField(default=False)

    class Meta:
        ordering = ["order"]
        unique_together = [("user", "slug")]

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
    title = models.CharField(max_length=500)
    notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=50, default="todo")
    order = models.PositiveIntegerField(default=0)
    due_date = models.DateField(null=True, blank=True)
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
            title=self.title,
            notes=self.notes,
            status="backlog",
            due_date=new_due,
            tags=list(self.tags),
            recurrence_days=self.recurrence_days,
            recurrence_from=self.recurrence_from,
        )
