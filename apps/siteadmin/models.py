import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


class SiteSettings(models.Model):
    """Singleton row (pk=1) holding site-wide configuration. Use SiteSettings.load()
    rather than querying directly."""

    MODE_PRIVATE = "private"
    MODE_INVITE_ONLY = "invite_only"
    MODE_OPEN = "open"
    MODE_CHOICES = [
        (MODE_PRIVATE, "Private — no one can join"),
        (MODE_INVITE_ONLY, "Invite-only — admins must invite users"),
        (MODE_OPEN, "Open — anyone can sign up"),
    ]

    signup_mode = models.CharField(max_length=20, choices=MODE_CHOICES, default=MODE_OPEN)

    @classmethod
    def load(cls) -> "SiteSettings":
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"signup_mode": cls.MODE_OPEN})
        return obj

    def __str__(self):
        return f"Site settings (signup: {self.signup_mode})"


class SiteInvite(models.Model):
    """A single-use, expiring invite that lets one email address create a vtodo
    account while signup_mode is invite_only. Consumed automatically the next
    time that email completes signup (see apps.siteadmin.selectors.consume_signup_slot)."""

    email = models.EmailField()
    token = models.CharField(max_length=64, unique=True, editable=False)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sent_site_invites",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def generate(cls, email: str, invited_by) -> "SiteInvite":
        token = secrets.token_urlsafe(32)
        expires_at = timezone.now() + timezone.timedelta(days=7)
        return cls.objects.create(email=email, token=token, invited_by=invited_by, expires_at=expires_at)

    @property
    def is_valid(self) -> bool:
        return self.accepted_at is None and timezone.now() < self.expires_at

    def __str__(self):
        return f"Site invite for {self.email}"
