import pytest
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.api.models import DeviceToken, hash_device_token
from apps.emailauth.models import EmailIdentity
from apps.siteadmin.models import SiteInvite, SiteSettings
from apps.users.models import User

CLIENT_ID = "test-client.apps.googleusercontent.com"


def _claims(**overrides):
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "email": "ada@example.com",
        "email_verified": True,
        "name": "Ada Lovelace",
        "picture": "https://example.com/ada.jpg",
    }
    claims.update(overrides)
    return claims


@pytest.fixture
def google_client_id(settings):
    settings.GOOGLE_CLIENT_ID = CLIENT_ID


@pytest.fixture
def accept_token(monkeypatch):
    def _accept(claims):
        monkeypatch.setattr(
            "apps.accounts.google_accounts.verify_google_id_token",
            lambda raw: claims,
        )

    return _accept


@pytest.mark.django_db
def test_get_returns_web_client_id(google_client_id):
    response = APIClient().get(reverse("google-sign-in"))

    assert response.status_code == 200
    assert response.data == {"client_id": CLIENT_ID}


@pytest.mark.django_db
def test_get_reports_when_google_is_not_configured(settings):
    settings.GOOGLE_CLIENT_ID = ""

    response = APIClient().get(reverse("google-sign-in"))

    assert response.status_code == 503
    assert "not configured" in response.data["detail"]


@pytest.mark.django_db
def test_post_creates_account_and_device_token(google_client_id, accept_token):
    accept_token(_claims())

    response = APIClient().post(
        reverse("google-sign-in"),
        {"id_token": "good-token", "device_name": "Pixel 9"},
        format="json",
    )

    assert response.status_code == 200
    identity = EmailIdentity.objects.get(email="ada@example.com")
    assert identity.verified is True
    assert identity.user.display_name == "Ada Lovelace"
    assert identity.user.avatar_url == "https://example.com/ada.jpg"
    key = response.data["token"]
    device = DeviceToken.objects.get(user=identity.user)
    assert device.name == "Pixel 9"
    assert device.key_hash == hash_device_token(key)
    assert key not in device.key_hash
    assert not Token.objects.filter(user=identity.user).exists()

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {key}")
    assert client.get(reverse("task-list")).status_code == 200


@pytest.mark.django_db
def test_post_reuses_existing_account_with_a_new_device_token(google_client_id, accept_token):
    user = User.objects.create_user(display_name="Kept")
    EmailIdentity.objects.create(user=user, email="Ada@Example.com", verified=False)
    existing, _ = Token.objects.get_or_create(user=user)
    accept_token(_claims(email="ada@example.com", name="New Name", picture="https://example.com/new.jpg"))

    response = APIClient().post(reverse("google-sign-in"), {"id_token": "good-token"}, format="json")

    assert response.status_code == 200
    assert response.data["token"] != existing.key
    assert Token.objects.get(user=user).key == existing.key
    assert DeviceToken.objects.filter(user=user).count() == 1
    assert EmailIdentity.objects.filter(user=user).count() == 1
    identity = EmailIdentity.objects.get(user=user)
    assert identity.verified is True
    user.refresh_from_db()
    assert user.display_name == "Kept"
    assert user.avatar_url == "https://example.com/new.jpg"


@pytest.mark.django_db
def test_post_rejects_a_token_google_would_reject(google_client_id, monkeypatch):
    def reject(raw, request, audience):
        assert raw == "nope"
        assert audience == CLIENT_ID
        raise ValueError("bad signature")

    monkeypatch.setattr("apps.accounts.google_accounts.id_token.verify_oauth2_token", reject)

    response = APIClient().post(reverse("google-sign-in"), {"id_token": "nope"}, format="json")

    assert response.status_code == 401
    assert not EmailIdentity.objects.exists()
    assert not DeviceToken.objects.exists()


@pytest.mark.django_db
def test_post_rejects_wrong_audience(google_client_id, monkeypatch):
    monkeypatch.setattr(
        "apps.accounts.google_accounts.id_token.verify_oauth2_token",
        lambda raw, request, audience: _claims(aud="other-client.apps.googleusercontent.com"),
    )

    response = APIClient().post(reverse("google-sign-in"), {"id_token": "good-token"}, format="json")

    assert response.status_code == 401
    assert not User.objects.exists()


@pytest.mark.django_db
def test_post_rejects_unverified_email(google_client_id, accept_token):
    accept_token(_claims(email_verified=False))

    response = APIClient().post(reverse("google-sign-in"), {"id_token": "good-token"}, format="json")

    assert response.status_code == 403
    assert response.data["detail"] == "Your account's email isn't verified."
    assert not EmailIdentity.objects.exists()


@pytest.mark.django_db
def test_post_requires_an_id_token(google_client_id):
    response = APIClient().post(reverse("google-sign-in"), {}, format="json")

    assert response.status_code == 401


@pytest.mark.django_db
def test_post_blocked_when_signups_are_private(google_client_id, accept_token):
    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_PRIVATE)
    accept_token(_claims(email="private@example.com"))

    response = APIClient().post(reverse("google-sign-in"), {"id_token": "good-token"}, format="json")

    assert response.status_code == 403
    assert response.data["detail"] == "vtodo isn't open for signups right now."
    assert not EmailIdentity.objects.filter(email="private@example.com").exists()


@pytest.mark.django_db
def test_post_invite_only_consumes_a_matching_invite(google_client_id, accept_token):
    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_INVITE_ONLY)
    invite = SiteInvite.generate("invited@example.com", invited_by=None)
    accept_token(_claims(email="invited@example.com"))

    response = APIClient().post(reverse("google-sign-in"), {"id_token": "good-token"}, format="json")

    assert response.status_code == 200
    invite.refresh_from_db()
    assert invite.accepted_at is not None
    assert EmailIdentity.objects.filter(email="invited@example.com").exists()


@pytest.mark.django_db
def test_post_invite_only_without_invite_creates_nothing(google_client_id, accept_token):
    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_INVITE_ONLY)
    accept_token(_claims(email="uninvited@example.com"))

    response = APIClient().post(reverse("google-sign-in"), {"id_token": "good-token"}, format="json")

    assert response.status_code == 403
    assert not EmailIdentity.objects.filter(email="uninvited@example.com").exists()


@pytest.mark.django_db
def test_post_refuses_a_disabled_account(google_client_id, accept_token):
    user = User.objects.create_user(is_active=False)
    EmailIdentity.objects.create(user=user, email="ada@example.com", verified=True)
    accept_token(_claims())

    response = APIClient().post(reverse("google-sign-in"), {"id_token": "good-token"}, format="json")

    assert response.status_code == 403
    assert response.data["detail"] == "This account is disabled."
    assert not DeviceToken.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_post_reports_when_google_is_not_configured(settings):
    settings.GOOGLE_CLIENT_ID = ""

    response = APIClient().post(reverse("google-sign-in"), {"id_token": "good-token"}, format="json")

    assert response.status_code == 503
    assert not User.objects.exists()
