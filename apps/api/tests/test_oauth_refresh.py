"""MCP clients refresh the same grant more than once, and sometimes late:
several sessions on one connector all reach the hourly expiry together, and
a client retries a refresh whose response it lost, sometimes minutes later.
None of that may sign anyone out. See config/settings.py:OAUTH2_PROVIDER and
apps/api/oauth_validators.py."""

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
    # A grant whose access token was issued a while ago, as at the hourly
    # refresh.
    AccessToken.objects.filter(pk=access.pk).update(updated=timezone.now() - timedelta(hours=1))
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


def _age_access_token(refresh, by):
    AccessToken.objects.filter(pk=RefreshToken.objects.get(pk=refresh.pk).access_token_id).update(
        updated=timezone.now() - by
    )


@pytest.mark.django_db
def test_refresh_keeps_the_same_refresh_token():
    user = User.objects.create_user(username="oauth-refresh-stable")
    application, refresh = _grant(user)

    response = _refresh(application, refresh.token)

    assert response.status_code == 200
    assert response.json()["refresh_token"] == refresh.token
    assert response.json()["access_token"] != "access-0"
    assert _api_status(response.json()["access_token"]) == 200


@pytest.mark.django_db
def test_refreshing_twice_in_a_row_hands_back_the_same_access_token():
    user = User.objects.create_user(username="oauth-refresh-race")
    application, refresh = _grant(user)

    first = _refresh(application, refresh.token)
    second = _refresh(application, refresh.token)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["access_token"] == first.json()["access_token"]
    assert 0 < second.json()["expires_in"] <= 3600
    assert _api_status(first.json()["access_token"]) == 200


@pytest.mark.django_db
def test_a_late_retry_of_the_same_refresh_token_still_works():
    """The case that used to revoke the whole grant: a client sends the
    refresh token again long after another refresh."""
    user = User.objects.create_user(username="oauth-refresh-late")
    application, refresh = _grant(user)

    first = _refresh(application, refresh.token)
    _age_access_token(refresh, timedelta(minutes=30))
    late = _refresh(application, refresh.token)

    assert late.status_code == 200
    assert late.json()["access_token"] != first.json()["access_token"]
    assert _api_status(late.json()["access_token"]) == 200
    assert RefreshToken.objects.get(pk=refresh.pk).revoked is None


@pytest.mark.django_db
def test_refresh_after_the_access_token_expired_works():
    user = User.objects.create_user(username="oauth-refresh-expired")
    application, refresh = _grant(user)
    AccessToken.objects.filter(token="access-0").update(expires=timezone.now() - timedelta(hours=2))

    response = _refresh(application, refresh.token)

    assert response.status_code == 200
    assert _api_status(response.json()["access_token"]) == 200


@pytest.mark.django_db
def test_replaying_a_refresh_token_rotated_before_the_switch_still_revokes_the_family():
    """Reuse protection still covers refresh tokens rotated before rotation
    was turned off."""
    user = User.objects.create_user(username="oauth-refresh-replay")
    application, refresh = _grant(user)
    live_access = AccessToken.objects.create(
        user=user,
        application=application,
        token="access-1",
        expires=timezone.now() + timedelta(hours=1),
        scope="tasks",
    )
    RefreshToken.objects.create(
        user=user,
        application=application,
        token="refresh-1",
        access_token=live_access,
        token_family=refresh.token_family,
    )
    RefreshToken.objects.filter(pk=refresh.pk).update(
        access_token=None, revoked=timezone.now() - timedelta(hours=1)
    )

    replay = _refresh(application, refresh.token)

    assert replay.status_code == 400
    assert _api_status("access-1") == 401
