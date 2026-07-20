from django.conf import settings
from django.db import models

from apps.integrations.skylight import crypto


class ExternalLink(models.Model):
    """
    Links a Task to a record in an external system (GitHub, Trello, Linear, etc.).
    Provider-specific data lives in metadata. Schema only for MVP — no provider logic.
    """

    class Provider(models.TextChoices):
        GITHUB = "github", "GitHub"
        TRELLO = "trello", "Trello"
        LINEAR = "linear", "Linear"
        SKYLIGHT = "skylight", "Skylight"

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


class SkylightConnection(models.Model):
    """A team's connection to a Skylight calendar frame. One per team.

    Skylight's password login is retired; the owner instead supplies a
    refresh_token (pulled once from their own logged-in browser session) which
    is stored encrypted. Skylight rotates the refresh_token on every use, so the
    sync job persists a new one each time it re-authenticates.
    """

    team = models.OneToOneField(
        "teams.Team",
        on_delete=models.CASCADE,
        related_name="skylight_connection",
    )
    # Skylight has no endpoint to discover which frame(s) belong to an account, so
    # the owner supplies this manually (found via their app/browser network traffic).
    frame_id = models.CharField(max_length=100)
    refresh_token_encrypted = models.TextField(blank=True, default="")
    token_encrypted = models.TextField(blank=True, default="")
    token_fetched_at = models.DateTimeField(null=True, blank=True)
    # Set once the owner picks a source calendar (auto-discovered via
    # GET /api/frames/{frame_id}/source_calendars after the first successful login).
    calendar_account_id = models.CharField(max_length=50, blank=True, default="")
    calendar_id = models.CharField(max_length=255, blank=True, default="")
    connected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="skylight_connections_made",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.TextField(blank=True, default="")

    def __str__(self):
        return f"Skylight({self.frame_id}) for {self.team}"

    @property
    def is_ready(self) -> bool:
        """A calendar has been picked, so sync can actually run."""
        return bool(self.calendar_account_id)

    def set_refresh_token(self, raw_refresh_token: str) -> None:
        self.refresh_token_encrypted = crypto.encrypt(raw_refresh_token)

    def get_refresh_token(self) -> str:
        if not self.refresh_token_encrypted:
            return ""
        return crypto.decrypt(self.refresh_token_encrypted)

    def set_token(self, raw_token: str) -> None:
        self.token_encrypted = crypto.encrypt(raw_token)

    def get_token(self) -> str:
        if not self.token_encrypted:
            return ""
        return crypto.decrypt(self.token_encrypted)


class SkylightMemberMapping(models.Model):
    """Maps a Skylight family member (category) to a vtodo team member, for
    assignee sync. Editable any time — not just at connect time — since both
    rosters change independently. A missing row or user=None both mean "unmapped";
    an unmapped category/assignee is left unassigned rather than guessed.
    """

    connection = models.ForeignKey(
        SkylightConnection,
        on_delete=models.CASCADE,
        related_name="member_mappings",
    )
    category_id = models.CharField(max_length=50)
    category_label = models.CharField(max_length=255, blank=True, default="")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="skylight_mappings",
    )

    class Meta:
        unique_together = [("connection", "category_id")]

    def __str__(self):
        who = self.user or "Unmapped"
        return f"{self.category_label or self.category_id} -> {who}"
