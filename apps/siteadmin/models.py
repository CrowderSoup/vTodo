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


class SiteInviteQuerySet(models.QuerySet):
    def pending(self):
        return self.filter(accepted_at__isnull=True, expires_at__gt=timezone.now())


class SiteInvite(models.Model):
    """A single-use, expiring invite that lets one email address create a vtodo
    account while signup_mode is invite_only. Consumed automatically the next
    time that email completes signup (see apps.siteadmin.selectors.consume_signup_slot).

    PENDING ──accept()──▶ ACCEPTED
       │
       └──expires_at passes──▶ EXPIRED

    ACCEPTED and EXPIRED are final. Only a PENDING invite can be accepted.
    """

    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        EXPIRED = "expired", "Expired"

    email = models.EmailField()
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sent_site_invites",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    objects = SiteInviteQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def generate(cls, email: str, invited_by) -> "SiteInvite":
        expires_at = timezone.now() + timezone.timedelta(days=7)
        return cls.objects.create(email=email, invited_by=invited_by, expires_at=expires_at)

    @property
    def state(self):
        if self.accepted_at is not None:
            return self.State.ACCEPTED
        if timezone.now() >= self.expires_at:
            return self.State.EXPIRED
        return self.State.PENDING

    def accept(self) -> None:
        """PENDING -> ACCEPTED"""
        if self.state != self.State.PENDING:
            raise ValueError(f"Can't accept a {self.state} invite.")
        self.accepted_at = timezone.now()
        self.save(update_fields=["accepted_at"])

    def __str__(self):
        return f"Site invite for {self.email}"
