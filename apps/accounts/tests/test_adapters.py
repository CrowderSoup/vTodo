import pytest
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from apps.accounts.adapters import SocialAccountAdapter
from apps.emailauth.models import EmailIdentity
from apps.users.models import User


@pytest.fixture
def request_factory(db):
    factory = RequestFactory()

    def _make():
        request = factory.get("/")
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    return _make


def _sociallogin(email="new@example.com", verified=True, uid="uid-1", extra_data=None):
    account = SocialAccount(provider="google", uid=uid, extra_data=extra_data or {})
    email_addresses = [EmailAddress(email=email, verified=verified, primary=True)] if email else []
    return SocialLogin(account=account, email_addresses=email_addresses)


@pytest.mark.django_db
def test_new_verified_email_creates_identity_and_user(request_factory):
    request = request_factory()
    sociallogin = _sociallogin(email="new@example.com", verified=True)

    SocialAccountAdapter().pre_social_login(request, sociallogin)

    identity = EmailIdentity.objects.get(email="new@example.com")
    assert identity.verified is True
    assert sociallogin.user == identity.user
    assert sociallogin.is_existing


@pytest.mark.django_db
def test_matching_existing_identity_reuses_account(request_factory):
    user = User.objects.create_user()
    identity = EmailIdentity.objects.create(user=user, email="existing@example.com", verified=False)
    request = request_factory()
    sociallogin = _sociallogin(email="existing@example.com", verified=True)

    SocialAccountAdapter().pre_social_login(request, sociallogin)

    assert EmailIdentity.objects.filter(email="existing@example.com").count() == 1
    identity.refresh_from_db()
    assert identity.verified is True
    assert sociallogin.user == user


@pytest.mark.django_db
def test_unverified_email_aborts_without_side_effects(request_factory):
    from allauth.core.exceptions import ImmediateHttpResponse

    request = request_factory()
    sociallogin = _sociallogin(email="unverified@example.com", verified=False)

    with pytest.raises(ImmediateHttpResponse):
        SocialAccountAdapter().pre_social_login(request, sociallogin)

    assert not EmailIdentity.objects.filter(email="unverified@example.com").exists()


@pytest.mark.django_db
def test_backfills_display_name_and_avatar_when_unset(request_factory):
    request = request_factory()
    sociallogin = _sociallogin(
        email="profile@example.com",
        verified=True,
        extra_data={"name": "Ada Lovelace", "picture": "https://example.com/ada.jpg"},
    )

    SocialAccountAdapter().pre_social_login(request, sociallogin)

    user = EmailIdentity.objects.get(email="profile@example.com").user
    assert user.display_name == "Ada Lovelace"
    assert user.avatar_url == "https://example.com/ada.jpg"


@pytest.mark.django_db
def test_does_not_overwrite_existing_display_name_and_avatar(request_factory):
    user = User.objects.create_user(display_name="Existing Name", avatar_url="https://example.com/existing.jpg")
    EmailIdentity.objects.create(user=user, email="keepmine@example.com", verified=True)
    request = request_factory()
    sociallogin = _sociallogin(
        email="keepmine@example.com",
        verified=True,
        extra_data={"name": "New Name", "picture": "https://example.com/new.jpg"},
    )

    SocialAccountAdapter().pre_social_login(request, sociallogin)

    user.refresh_from_db()
    assert user.display_name == "Existing Name"
    assert user.avatar_url == "https://example.com/existing.jpg"


@pytest.mark.django_db
def test_repeat_login_short_circuits(request_factory, django_assert_num_queries):
    user = User.objects.create_user()
    account = SocialAccount(provider="google", uid="uid-existing", user=user)
    sociallogin = SocialLogin(user=user, account=account)
    request = request_factory()

    with django_assert_num_queries(1):
        # is_existing itself issues one query (checking the user still exists);
        # nothing else should run once it short-circuits.
        SocialAccountAdapter().pre_social_login(request, sociallogin)
