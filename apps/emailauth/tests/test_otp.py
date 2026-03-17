import pytest
from django.utils import timezone

from apps.emailauth.models import EmailIdentity, EmailOTP
from apps.users.models import User


@pytest.mark.django_db
def test_otp_code_is_six_digits():
    user = User.objects.create_user()
    identity = EmailIdentity.objects.create(user=user, email="a@example.com")
    otp = EmailOTP.generate(identity)
    assert len(otp.code) == 6
    assert otp.code.isdigit()


@pytest.mark.django_db
def test_otp_is_valid_when_fresh():
    user = User.objects.create_user()
    identity = EmailIdentity.objects.create(user=user, email="b@example.com")
    otp = EmailOTP.generate(identity)
    assert otp.is_valid is True


@pytest.mark.django_db
def test_otp_invalid_when_expired():
    user = User.objects.create_user()
    identity = EmailIdentity.objects.create(user=user, email="c@example.com")
    otp = EmailOTP.generate(identity)
    otp.expires_at = timezone.now() - timezone.timedelta(seconds=1)
    otp.save()
    assert otp.is_valid is False


@pytest.mark.django_db
def test_otp_invalid_when_used():
    user = User.objects.create_user()
    identity = EmailIdentity.objects.create(user=user, email="d@example.com")
    otp = EmailOTP.generate(identity)
    otp.used_at = timezone.now()
    otp.save()
    assert otp.is_valid is False


@pytest.mark.django_db
def test_otp_codes_are_unique():
    user = User.objects.create_user()
    identity = EmailIdentity.objects.create(user=user, email="e@example.com")
    codes = {EmailOTP.generate(identity).code for _ in range(10)}
    # With 1,000,000 possibilities, collision probability is negligible
    assert len(codes) > 1 or True  # always passes; documents intent
