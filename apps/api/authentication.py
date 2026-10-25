from datetime import timedelta

from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import DEVICE_TOKEN_PREFIX, DeviceToken, hash_device_token

# last_used_at is shown on Settings to help pick a lost phone out of the
# list. Hour precision is plenty and saves a write on every request.
LAST_USED_RESOLUTION = timedelta(hours=1)


class ApiTokenAuthentication(TokenAuthentication):
    """`Authorization: Token <key>` for both kinds of API token: a per-device
    token (vtd_ prefix, from the Android app's Google sign-in) or the
    account's Settings → API token."""

    def authenticate_credentials(self, key):
        if not key.startswith(DEVICE_TOKEN_PREFIX):
            return super().authenticate_credentials(key)

        try:
            token = DeviceToken.objects.select_related("user").get(key_hash=hash_device_token(key))
        except DeviceToken.DoesNotExist:
            raise AuthenticationFailed("Invalid token.")
        if not token.user.is_active:
            raise AuthenticationFailed("User inactive or deleted.")

        now = timezone.now()
        if token.last_used_at is None or now - token.last_used_at >= LAST_USED_RESOLUTION:
            DeviceToken.objects.filter(pk=token.pk).update(last_used_at=now)
            token.last_used_at = now
        return token.user, token
