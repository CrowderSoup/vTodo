import pytest

from apps.users.models import User
from apps.users.selectors import is_admin


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
