from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from oauth2_provider.models import get_access_token_model, get_application_model
from rest_framework.test import APIClient

Application = get_application_model()
AccessToken = get_access_token_model()


@pytest.fixture(autouse=True)
def _clear_cache():
    # Throttle counters and the Google cert cache live in the cache, which
    # the test settings keep in memory for the whole run.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def oauth_client_for():
    """An APIClient presenting an OAuth access token for `user`, the way
    mcp_server does when it forwards a remote MCP client's token."""

    def _make(user, scope="tasks", expires_in=timedelta(hours=1), resource=None):
        application = Application.objects.create(
            user=user,
            name="test client",
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        )
        token = AccessToken.objects.create(
            user=user,
            application=application,
            token="test-access-token-" + user.username,
            expires=timezone.now() + expires_in,
            scope=scope,
            resource=resource or [],
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        return client

    return _make
