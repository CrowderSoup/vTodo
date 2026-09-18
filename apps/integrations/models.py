from django.conf import settings
from django.db import models

from apps.integrations import crypto


class ExternalLink(models.Model):
    """
    Links a Task to a record in an external system (GitHub, Trello, Linear, etc.).
    Provider-specific data lives in metadata. Schema only for MVP — no provider logic.
    """

    class Provider(models.TextChoices):
        GITHUB = "github", "GitHub"
        TRELLO = "trello", "Trello"
        LINEAR = "linear", "Linear"
        GOOGLE_CALENDAR = "google_calendar", "Google Calendar"

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


class GoogleCalendarConnection(models.Model):
    """A user's connection to their own dedicated "vTodo" Google Calendar.

    Google's access tokens are short-lived (~1hr) and cheap to mint, so only the
    refresh token is persisted -- a fresh access token is fetched per sync run
    instead of caching one across requests.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="google_calendar_connection",
    )
    # The dedicated calendar's id, from calendars.insert at connect time.
    calendar_id = models.CharField(max_length=255)
    refresh_token_encrypted = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.TextField(blank=True, default="")

    def __str__(self):
        return f"Google Calendar for {self.user}"

    def set_refresh_token(self, raw_refresh_token: str) -> None:
        self.refresh_token_encrypted = crypto.encrypt(raw_refresh_token)

    def get_refresh_token(self) -> str:
        return crypto.decrypt(self.refresh_token_encrypted)
