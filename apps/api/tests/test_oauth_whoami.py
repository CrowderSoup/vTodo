from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from oauth2_provider.models import get_access_token_model, get_application_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.users.models import User

Application = get_application_model()
AccessToken = get_access_token_model()


@pytest.fixture
def oauth_client_for():
    def _make(user, scope="tasks", expires_in=timedelta(hours=1)):
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
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        return client

    return _make


@pytest.mark.django_db
def test_whoami_requires_auth():
    client = APIClient()

    response = client.get(reverse("mcp-whoami"))

    assert response.status_code == 401


@pytest.mark.django_db
def test_whoami_rejects_garbage_token():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")

    response = client.get(reverse("mcp-whoami"))

    assert response.status_code == 401


@pytest.mark.django_db
def test_whoami_rejects_expired_token(oauth_client_for):
    user = User.objects.create_user()
    client = oauth_client_for(user, expires_in=timedelta(hours=-1))

    response = client.get(reverse("mcp-whoami"))

    assert response.status_code == 401


@pytest.mark.django_db
def test_whoami_rejects_insufficient_scope(oauth_client_for):
    user = User.objects.create_user()
    client = oauth_client_for(user, scope="read")

    response = client.get(reverse("mcp-whoami"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_whoami_returns_the_callers_own_api_token(oauth_client_for):
    user = User.objects.create_user(username="whoami-user")
    expected_token, _ = Token.objects.get_or_create(user=user)
    client = oauth_client_for(user)

    response = client.get(reverse("mcp-whoami"))

    assert response.status_code == 200
    assert response.data == {
        "user_id": user.pk,
        "username": "whoami-user",
        "api_token": expected_token.key,
    }
