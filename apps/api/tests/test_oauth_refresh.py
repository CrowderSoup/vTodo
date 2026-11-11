"""Refresh-token rotation must survive MCP clients that refresh the same
token twice: several sessions sharing one connector all hit their hourly
expiry together, and a client retries a refresh whose response it lost."""

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from oauth2_provider.models import AccessToken, Application, RefreshToken
from rest_framework.test import APIClient

from apps.users.models import User


def _grant(user):
    application = Application.objects.create(
        user=user,
        name="mcp client",
        client_type=Application.CLIENT_PUBLIC,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
    )
    access = AccessToken.objects.create(
        user=user,
        application=application,
        token="access-0",
        expires=timezone.now() + timedelta(hours=1),
        scope="tasks",
    )
    refresh = RefreshToken.objects.create(
        user=user,
        application=application,
        token="refresh-0",
        access_token=access,
        token_family=uuid.uuid4(),
    )
    return application, refresh


def _refresh(application, refresh_token):
    return APIClient().post(
        reverse("oauth2_provider:token"),
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": application.client_id,
        },
    )


def _api_status(access_token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
    return client.get(reverse("task-list")).status_code


@pytest.mark.django_db
def test_refreshing_the_same_token_twice_does_not_revoke_the_session():
    user = User.objects.create_user(username="oauth-refresh-race")
    application, refresh = _grant(user)

    first = _refresh(application, refresh.token)
    second = _refresh(application, refresh.token)

    assert first.status_code == 200
    assert second.status_code == 200
    assert _api_status(first.json()["access_token"]) == 200
    assert _api_status(second.json()["access_token"]) == 200


@pytest.mark.django_db
def test_replaying_a_long_superseded_refresh_token_still_revokes_the_family(settings):
    user = User.objects.create_user(username="oauth-refresh-replay")
    application, refresh = _grant(user)

    rotated = _refresh(application, refresh.token)
    assert rotated.status_code == 200
    RefreshToken.objects.filter(pk=refresh.pk).update(revoked=timezone.now() - timedelta(hours=1))

    replay = _refresh(application, refresh.token)

    assert replay.status_code == 400
    assert _api_status(rotated.json()["access_token"]) == 401
