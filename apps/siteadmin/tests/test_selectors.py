import pytest
from django.utils import timezone

from apps.siteadmin.models import SiteInvite, SiteSettings
from apps.siteadmin.selectors import consume_signup_slot, signup_allowed


@pytest.mark.django_db
def test_open_mode_allows_any_email():
    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_OPEN)
    assert signup_allowed("anyone@example.com") is True


@pytest.mark.django_db
def test_private_mode_blocks_everyone():
    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_PRIVATE)
    assert signup_allowed("anyone@example.com") is False


@pytest.mark.django_db
def test_invite_only_blocks_without_invite():
    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_INVITE_ONLY)
    assert signup_allowed("nobody@example.com") is False


@pytest.mark.django_db
def test_invite_only_allows_with_valid_invite():
    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_INVITE_ONLY)
    SiteInvite.generate("invited@example.com", invited_by=None)
    assert signup_allowed("invited@example.com") is True


@pytest.mark.django_db
def test_invite_only_ignores_expired_invite():
    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_INVITE_ONLY)
    invite = SiteInvite.generate("expired@example.com", invited_by=None)
    invite.expires_at = timezone.now() - timezone.timedelta(days=1)
    invite.save(update_fields=["expires_at"])
    assert signup_allowed("expired@example.com") is False


@pytest.mark.django_db
def test_invite_only_ignores_already_accepted_invite():
    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_INVITE_ONLY)
    invite = SiteInvite.generate("used@example.com", invited_by=None)
    invite.accepted_at = timezone.now()
    invite.save(update_fields=["accepted_at"])
    assert signup_allowed("used@example.com") is False


@pytest.mark.django_db
def test_consume_signup_slot_marks_invite_accepted():
    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_INVITE_ONLY)
    invite = SiteInvite.generate("consume@example.com", invited_by=None)

    assert consume_signup_slot("consume@example.com") is True

    invite.refresh_from_db()
    assert invite.accepted_at is not None
    # A second attempt for the same email can't reuse the now-accepted invite.
    assert consume_signup_slot("consume@example.com") is False


@pytest.mark.django_db
def test_consume_signup_slot_open_mode_does_not_touch_invites():
    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_OPEN)
    assert consume_signup_slot("nobody-invited@example.com") is True
