from datetime import timedelta

import pytest
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.users.models import User

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
def test_whoami_accepts_token_restricted_to_the_mcp_resource(oauth_client_for, settings):
    """Regression test: a token minted for mcp_server's own resource
    identifier (RFC 8707) -- exactly what Claude presents to whoami in
    production -- must still resolve, even though whoami itself is on a
    different host than that resource."""
    settings.VTODO_MCP_RESOURCE_URL = "https://mcp.vtodo.crowdersoup.com/mcp"
    user = User.objects.create_user(username="whoami-resource-user")
    client = oauth_client_for(user, resource=["https://mcp.vtodo.crowdersoup.com/mcp"])

    response = client.get(reverse("mcp-whoami"))

    assert response.status_code == 200
    assert response.data == {"user_id": user.pk, "username": "whoami-resource-user"}


@pytest.mark.django_db
def test_whoami_never_returns_or_creates_a_drf_token(oauth_client_for):
    """An hour-long, revocable OAuth grant must not be exchangeable for the
    user's permanent DRF API token."""
    user = User.objects.create_user(username="whoami-user")
    client = oauth_client_for(user)

    response = client.get(reverse("mcp-whoami"))

    assert response.status_code == 200
    assert response.data == {"user_id": user.pk, "username": "whoami-user"}
    assert "api_token" not in response.data
    assert not Token.objects.filter(user=user).exists()
