from django.db import models


class ExternalLink(models.Model):
    """
    Links a Task to a record in an external system (GitHub, Trello, Linear, etc.).
    Provider-specific data lives in metadata. Schema only for MVP — no provider logic.
    """

    class Provider(models.TextChoices):
        GITHUB = "github", "GitHub"
        TRELLO = "trello", "Trello"
        LINEAR = "linear", "Linear"

    task = models.ForeignKey(
        "tasks.Task",
        on_delete=models.CASCADE,
        related_name="external_links",
    )
    provider = models.CharField(max_length=50, choices=Provider.choices)
    external_id = models.CharField(max_length=255)
    external_url = models.URLField(max_length=2000, blank=True, default="")
    synced_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = [("task", "provider", "external_id")]

    def __str__(self):
        return f"{self.provider}:{self.external_id} -> {self.task}"
