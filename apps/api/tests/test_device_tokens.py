from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.api.models import DeviceToken
from apps.users.models import User


def _client(key):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {key}")
    return client


@pytest.mark.django_db
def test_device_token_authenticates_and_records_use():
    user = User.objects.create_user()
    device, key = DeviceToken.issue(user, "Pixel 9")

    response = _client(key).get(reverse("task-list"))

    assert response.status_code == 200
    device.refresh_from_db()
    assert device.last_used_at is not None


@pytest.mark.django_db
def test_device_token_last_used_is_written_at_most_hourly():
    user = User.objects.create_user()
    device, key = DeviceToken.issue(user)
    recent = timezone.now() - timedelta(minutes=10)
    DeviceToken.objects.filter(pk=device.pk).update(last_used_at=recent)

    _client(key).get(reverse("task-list"))

    device.refresh_from_db()
    assert device.last_used_at == recent


@pytest.mark.django_db
def test_unknown_device_token_is_rejected():
    response = _client("vtd_not-a-real-token").get(reverse("task-list"))

    assert response.status_code == 401


@pytest.mark.django_db
def test_device_token_of_inactive_user_is_rejected():
    user = User.objects.create_user(is_active=False)
    _, key = DeviceToken.issue(user)

    assert _client(key).get(reverse("task-list")).status_code == 401


@pytest.mark.django_db
def test_settings_token_still_authenticates():
    user = User.objects.create_user()
    token = Token.objects.create(user=user)

    assert _client(token.key).get(reverse("task-list")).status_code == 200


@pytest.mark.django_db
def test_sign_out_revokes_only_the_calling_device():
    user = User.objects.create_user()
    _, phone = DeviceToken.issue(user, "Phone")
    tablet, tablet_key = DeviceToken.issue(user, "Tablet")

    response = _client(phone).post(reverse("sign-out"))

    assert response.status_code == 204
    assert list(DeviceToken.objects.filter(user=user)) == [tablet]
    assert _client(phone).get(reverse("task-list")).status_code == 401
    assert _client(tablet_key).get(reverse("task-list")).status_code == 200


@pytest.mark.django_db
def test_sign_out_with_settings_token_keeps_it():
    user = User.objects.create_user()
    token = Token.objects.create(user=user)

    response = _client(token.key).post(reverse("sign-out"))

    assert response.status_code == 204
    assert Token.objects.filter(pk=token.pk).exists()


@pytest.mark.django_db
def test_sign_out_requires_a_token():
    assert APIClient().post(reverse("sign-out")).status_code == 401


@pytest.mark.django_db
def test_settings_lists_and_revokes_own_devices(client):
    user = User.objects.create_user()
    other = User.objects.create_user()
    mine, key = DeviceToken.issue(user, "My phone")
    theirs, _ = DeviceToken.issue(other, "Their phone")
    client.force_login(user)

    page = client.get(reverse("users:settings-api"))
    assert b"My phone" in page.content
    assert b"Their phone" not in page.content

    client.post(reverse("users:device-revoke", args=[theirs.pk]))
    assert DeviceToken.objects.filter(pk=theirs.pk).exists()

    response = client.post(reverse("users:device-revoke", args=[mine.pk]))
    assert response.status_code == 200
    assert not DeviceToken.objects.filter(pk=mine.pk).exists()
    assert _client(key).get(reverse("task-list")).status_code == 401
