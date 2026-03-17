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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["order", "created_at"]

    def __str__(self):
        return self.title
