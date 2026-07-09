import pytest
from django.core import mail
from django.urls import reverse

from apps.emailauth.models import EmailIdentity, EmailOTP
from apps.users.models import User


# ---------------------------------------------------------------------------
# RequestOTPView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_request_otp_sends_email(client):
    """Submitting a valid email triggers an OTP email."""
    response = client.post(
        reverse("emailauth:request"),
        {"email": "user@example.com"},
    )
    assert response.status_code == 302
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["user@example.com"]
    assert "login code" in mail.outbox[0].subject.lower()


@pytest.mark.django_db
def test_request_otp_creates_identity_for_new_email(client):
    """A brand-new email address gets an EmailIdentity created for it."""
    client.post(reverse("emailauth:request"), {"email": "new@example.com"})
    assert EmailIdentity.objects.filter(email="new@example.com").exists()


@pytest.mark.django_db
def test_request_otp_reuses_existing_identity(client):
    """An existing EmailIdentity is not duplicated."""
    user = User.objects.create_user()
    EmailIdentity.objects.create(user=user, email="existing@example.com")

    client.post(reverse("emailauth:request"), {"email": "existing@example.com"})
    assert EmailIdentity.objects.filter(email="existing@example.com").count() == 1


@pytest.mark.django_db
def test_request_otp_empty_email_redirects_with_error(client):
    """Submitting an empty email redirects back without sending email."""
    response = client.post(reverse("emailauth:request"), {"email": ""})
    assert response.status_code == 302
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_request_otp_rate_limited(client):
    """After too many attempts the view rejects further requests."""
    email = "rate@example.com"
    for _ in range(3):
        client.post(reverse("emailauth:request"), {"email": email})

    mail.outbox.clear()
    response = client.post(reverse("emailauth:request"), {"email": email})
    assert response.status_code == 302
    assert len(mail.outbox) == 0


# ---------------------------------------------------------------------------
# VerifyOTPView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_verify_otp_logs_user_in(client):
    """Submitting the correct OTP code logs the user in and redirects."""
    user = User.objects.create_user()
    identity = EmailIdentity.objects.create(user=user, email="v@example.com")
    otp = EmailOTP.generate(identity)

    session = client.session
    session["email_identity_pk"] = identity.pk
    session.save()

    response = client.post(reverse("emailauth:verify"), {"code": otp.code})
    assert response.status_code == 302
    assert "_auth_user_id" in client.session


@pytest.mark.django_db
def test_verify_otp_wrong_code_shows_error(client):
    """Submitting a wrong code stays on the verify page."""
    user = User.objects.create_user()
    identity = EmailIdentity.objects.create(user=user, email="w@example.com")
    EmailOTP.generate(identity)

    session = client.session
    session["email_identity_pk"] = identity.pk
    session.save()

    response = client.post(reverse("emailauth:verify"), {"code": "000000"})
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_verify_otp_no_session_redirects(client):
    """Accessing verify without a session redirects to login."""
    response = client.get(reverse("emailauth:verify"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_verify_otp_marks_code_used(client):
    """After a successful verify the OTP is marked as used."""
    user = User.objects.create_user()
    identity = EmailIdentity.objects.create(user=user, email="used@example.com")
    otp = EmailOTP.generate(identity)

    session = client.session
    session["email_identity_pk"] = identity.pk
    session.save()

    client.post(reverse("emailauth:verify"), {"code": otp.code})

    otp.refresh_from_db()
    assert otp.used_at is not None


# ---------------------------------------------------------------------------
# next= redirect preservation (e.g. team invite links)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_request_otp_stashes_next_in_session(client):
    client.post(
        reverse("emailauth:request"),
        {"email": "next@example.com", "next": "/teams/invite/abc/accept/"},
    )
    assert client.session["login_next"] == "/teams/invite/abc/accept/"


@pytest.mark.django_db
def test_request_otp_ignores_unsafe_next(client):
    client.post(
        reverse("emailauth:request"),
        {"email": "unsafe@example.com", "next": "https://evil.example.com/"},
    )
    assert "login_next" not in client.session


@pytest.mark.django_db
def test_request_otp_empty_email_preserves_next_on_redirect(client):
    response = client.post(
        reverse("emailauth:request"),
        {"email": "", "next": "/teams/invite/abc/accept/"},
    )
    assert response.status_code == 302
    assert "next=%2Fteams%2Finvite%2Fabc%2Faccept%2F" in response["Location"]


@pytest.mark.django_db
def test_verify_otp_redirects_to_stashed_next(client):
    user = User.objects.create_user()
    identity = EmailIdentity.objects.create(user=user, email="next2@example.com")
    otp = EmailOTP.generate(identity)

    session = client.session
    session["email_identity_pk"] = identity.pk
    session["login_next"] = "/teams/invite/abc/accept/"
    session.save()

    response = client.post(reverse("emailauth:verify"), {"code": otp.code})
    assert response.status_code == 302
    assert response["Location"] == "/teams/invite/abc/accept/"
    assert "login_next" not in client.session


@pytest.mark.django_db
def test_verify_otp_falls_back_to_board_without_next(client):
    user = User.objects.create_user()
    identity = EmailIdentity.objects.create(user=user, email="noboard@example.com")
    otp = EmailOTP.generate(identity)

    session = client.session
    session["email_identity_pk"] = identity.pk
    session.save()

    response = client.post(reverse("emailauth:verify"), {"code": otp.code})
    assert response.status_code == 302
    assert response["Location"] == reverse("boards:board")
