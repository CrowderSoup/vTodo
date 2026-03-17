import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


class EmailIdentity(models.Model):
    """Links a User to an email address for OTP-based login."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_identities",
    )
    email = models.EmailField(unique=True)
    verified = models.BooleanField(default=False)  # True after first successful OTP login
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email


class EmailOTP(models.Model):
    """
    A single-use 6-digit OTP code for email login.
    Created when a login is requested, consumed on successful verification.
    """

    identity = models.ForeignKey(
        EmailIdentity,
        on_delete=models.CASCADE,
        related_name="otps",
    )
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def generate(cls, identity: "EmailIdentity") -> "EmailOTP":
        """Create a new OTP for the given identity."""
        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = timezone.now() + timezone.timedelta(minutes=15)
        return cls.objects.create(identity=identity, code=code, expires_at=expires_at)

    @property
    def is_valid(self) -> bool:
        return self.used_at is None and timezone.now() < self.expires_at

    def __str__(self):
        return f"OTP for {self.identity.email}"
