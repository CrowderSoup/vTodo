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


class GoogleCalendarConnectionQuerySet(models.QuerySet):
    def syncable(self):
        """Connections the periodic sync should run: HEALTHY or FAILING."""
        return self.filter(is_active=True).exclude(calendar_id="")


class GoogleCalendarConnection(models.Model):
    """A user's connection to their own dedicated "vTodo" Google Calendar.

    Google's access tokens are short-lived (~1hr) and cheap to mint, so only the
    refresh token is persisted -- a fresh access token is fetched per sync run
    instead of caching one across requests.

    A connection is in one of four states (`state`):

        CONNECTING ──calendar_created──▶ HEALTHY ◀──synced── FAILING
                                           │  ──sync_failed──▶  │
                                           └──────┬─────────────┘
                                                  │ token_revoked
                                                  ▼
                                               REVOKED ──connected──▶ CONNECTING

    CONNECTING has a refresh token but no calendar yet. If creating the
    calendar fails it stays there, and sync skips it until the user connects
    again. Disconnecting deletes the row from any state.
    """

    class State(models.TextChoices):
        CONNECTING = "connecting", "Connecting"
        HEALTHY = "healthy", "Healthy"
        FAILING = "failing", "Failing"
        REVOKED = "revoked", "Revoked"

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

    objects = GoogleCalendarConnectionQuerySet.as_manager()

    def __str__(self):
        return f"Google Calendar for {self.user}"

    @property
    def state(self):
        if not self.is_active:
            return self.State.REVOKED
        if not self.calendar_id:
            return self.State.CONNECTING
        if self.last_sync_error:
            return self.State.FAILING
        return self.State.HEALTHY

    def connected(self, raw_refresh_token: str) -> None:
        """Google granted access (again). -> CONNECTING"""
        self.set_refresh_token(raw_refresh_token)
        self.is_active = True
        self.calendar_id = ""
        self.last_sync_error = ""
        self.save(update_fields=["refresh_token_encrypted", "is_active", "calendar_id", "last_sync_error"])

    def calendar_created(self, calendar_id: str) -> None:
        """CONNECTING -> HEALTHY"""
        self.calendar_id = calendar_id
        self.save(update_fields=["calendar_id"])

    def synced(self) -> None:
        """HEALTHY or FAILING -> HEALTHY"""
        from django.utils import timezone

        self.last_synced_at = timezone.now()
        self.last_sync_error = ""
        self.save(update_fields=["last_synced_at", "last_sync_error"])

    def sync_failed(self, error) -> None:
        """HEALTHY or FAILING -> FAILING. Retried next cycle."""
        self.last_sync_error = str(error)
        self.save(update_fields=["last_sync_error"])

    def token_revoked(self, error) -> None:
        """Google rejected the refresh token for good. -> REVOKED"""
        self.is_active = False
        self.last_sync_error = str(error)
        self.save(update_fields=["is_active", "last_sync_error"])

    def set_refresh_token(self, raw_refresh_token: str) -> None:
        self.refresh_token_encrypted = crypto.encrypt(raw_refresh_token)

    def get_refresh_token(self) -> str:
        return crypto.decrypt(self.refresh_token_encrypted)
