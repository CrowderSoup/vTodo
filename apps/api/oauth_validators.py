from datetime import timedelta

from django.utils import timezone
from oauth2_provider.models import get_access_token_model, get_refresh_token_model
from oauth2_provider.oauth2_validators import OAuth2Validator
from oauth2_provider.settings import oauth2_settings

AccessToken = get_access_token_model()
RefreshToken = get_refresh_token_model()


class VtodoOAuth2Validator(OAuth2Validator):
    """OAUTH2_VALIDATOR_CLASS (config/settings.py:OAUTH2_PROVIDER).

    Refresh tokens don't rotate here, so one refresh token stays valid for
    the life of the grant. Refreshing gives the grant a new access token and
    the old one stops working. If the grant was already refreshed within the
    grace period, the caller gets that same access token instead of a new one.

    Without that, two callers refreshing the same grant at about the same time
    each make a new token. The second one cancels the first, and the first
    caller's next tool call fails even though it did nothing wrong.
    """

    def _save_bearer_token(self, token, request, *args, **kwargs):
        if self._reuse_fresh_access_token(token, request):
            return
        super()._save_bearer_token(token, request, *args, **kwargs)

    def _reuse_fresh_access_token(self, token, request) -> bool:
        if request.grant_type != "refresh_token" or self.rotate_refresh_token(request):
            return False
        refresh = getattr(request, "refresh_token_instance", None)
        if not isinstance(refresh, RefreshToken) or refresh.access_token_id is None:
            return False

        # save_bearer_token runs this inside a transaction. The row lock makes
        # a concurrent refresh of the same grant wait here, then see this one.
        access = AccessToken.objects.select_for_update().filter(pk=refresh.access_token_id).first()
        if access is None or not access.token or access.is_expired():
            return False
        now = timezone.now()
        if access.updated < now - timedelta(seconds=oauth2_settings.REFRESH_TOKEN_GRACE_PERIOD_SECONDS):
            return False

        token["access_token"] = access.token
        token["expires_in"] = max(1, int((access.expires - now).total_seconds()))
        token["scope"] = access.scope
        return True
