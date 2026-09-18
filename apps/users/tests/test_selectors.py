import hashlib
from datetime import timedelta

import pytest

from apps.users.models import User
from apps.users.selectors import gravatar_url, is_admin


@pytest.mark.django_db
def test_is_admin_true_for_verified_admin_email(settings):
    settings.ADMIN_EMAILS = ["admin@example.com"]
    user = User.objects.create_user()
    user.email_identities.create(email="admin@example.com", verified=True)
    assert is_admin(user) is True


@pytest.mark.django_db
def test_is_admin_false_for_non_admin_email(settings):
    settings.ADMIN_EMAILS = ["admin@example.com"]
    user = User.objects.create_user()
    user.email_identities.create(email="someone@example.com", verified=True)
    assert is_admin(user) is False


@pytest.mark.django_db
def test_is_admin_false_when_unverified(settings):
    settings.ADMIN_EMAILS = ["admin@example.com"]
    user = User.objects.create_user()
    user.email_identities.create(email="admin@example.com", verified=False)
    assert is_admin(user) is False


@pytest.mark.django_db
def test_is_admin_false_for_anonymous_user(settings):
    from django.contrib.auth.models import AnonymousUser

    settings.ADMIN_EMAILS = ["admin@example.com"]
    assert is_admin(AnonymousUser()) is False


@pytest.mark.django_db
def test_gravatar_url_hashes_oldest_verified_email():
    user = User.objects.create_user()
    user.email_identities.create(email="newer@example.com", verified=True)
    identity = user.email_identities.create(email="older@example.com", verified=True)
    identity.created_at -= timedelta(days=1)
    identity.save(update_fields=["created_at"])

    digest = hashlib.sha256(b"older@example.com").hexdigest()
    assert gravatar_url(user) == f"https://www.gravatar.com/avatar/{digest}?s=160&d=404"


@pytest.mark.django_db
def test_gravatar_url_ignores_unverified_email():
    user = User.objects.create_user()
    user.email_identities.create(email="unverified@example.com", verified=False)
    assert gravatar_url(user) == ""


@pytest.mark.django_db
def test_gravatar_url_empty_for_anonymous_user():
    from django.contrib.auth.models import AnonymousUser

    assert gravatar_url(AnonymousUser()) == ""
