import pytest
from django.core import mail
from django.urls import reverse

from apps.siteadmin.models import SiteInvite, SiteSettings
from apps.siteadmin.views import INVITE_RATE_LIMIT
from apps.users.models import User


@pytest.fixture
def admin_client(client, db, settings):
    user = User.objects.create_user()
    user.email_identities.create(email="admin@example.com", verified=True)
    settings.ADMIN_EMAILS = ["admin@example.com"]
    client.force_login(user)
    return client, user


@pytest.fixture
def member_client(client, db, settings):
    user = User.objects.create_user()
    user.email_identities.create(email="member@example.com", verified=True)
    settings.ADMIN_EMAILS = ["admin@example.com"]
    client.force_login(user)
    return client, user


@pytest.mark.django_db
def test_dashboard_requires_login(client):
    response = client.get(reverse("siteadmin:dashboard"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_dashboard_forbidden_for_non_admin(member_client):
    client, _ = member_client
    response = client.get(reverse("siteadmin:dashboard"))
    assert response.status_code == 403


@pytest.mark.django_db
def test_dashboard_loads_for_admin(admin_client):
    client, _ = admin_client
    response = client.get(reverse("siteadmin:dashboard"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_signup_mode_update_persists(admin_client):
    client, _ = admin_client
    response = client.post(
        reverse("siteadmin:signup-mode-update"), {"signup_mode": SiteSettings.MODE_PRIVATE}
    )
    assert response.status_code == 302
    assert SiteSettings.load().signup_mode == SiteSettings.MODE_PRIVATE


@pytest.mark.django_db
def test_signup_mode_update_rejects_invalid_value(admin_client):
    client, _ = admin_client
    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_OPEN)
    client.post(reverse("siteadmin:signup-mode-update"), {"signup_mode": "nonsense"})
    assert SiteSettings.load().signup_mode == SiteSettings.MODE_OPEN


@pytest.mark.django_db
def test_signup_mode_update_forbidden_for_non_admin(member_client):
    client, _ = member_client
    response = client.post(
        reverse("siteadmin:signup-mode-update"), {"signup_mode": SiteSettings.MODE_PRIVATE}
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_invite_create_sends_email(admin_client):
    client, _ = admin_client
    response = client.post(reverse("siteadmin:invite-create"), {"email": "new@example.com"})
    assert response.status_code == 302
    assert len(mail.outbox) == 1
    assert SiteInvite.objects.filter(email="new@example.com").exists()


@pytest.mark.django_db
def test_invite_create_rate_limited(admin_client):
    client, _ = admin_client
    for _ in range(INVITE_RATE_LIMIT):
        client.post(reverse("siteadmin:invite-create"), {"email": "rate@example.com"})

    mail.outbox.clear()
    response = client.post(reverse("siteadmin:invite-create"), {"email": "rate@example.com"})
    assert response.status_code == 302
    assert len(mail.outbox) == 0
