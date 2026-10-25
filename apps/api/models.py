import hashlib
import secrets

from django.conf import settings
from django.db import models

DEVICE_TOKEN_PREFIX = "vtd_"


def hash_device_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class DeviceToken(models.Model):
    """An API token for one signed-in device (the Android app's Google
    sign-in). Unlike the single Settings → API token, each phone gets its own,
    so signing out on one, or revoking a lost one from Settings, leaves the
    rest alone. Only a hash of the key is stored; the raw key is shown to the
    device once."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="device_tokens",
    )
    name = models.CharField(max_length=100, blank=True, default="")
    key_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name or f"Device {self.pk}"

    @classmethod
    def issue(cls, user, name: str = "") -> tuple["DeviceToken", str]:
        raw = DEVICE_TOKEN_PREFIX + secrets.token_urlsafe(32)
        token = cls.objects.create(user=user, name=name[:100], key_hash=hash_device_token(raw))
        return token, raw
