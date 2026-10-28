import pytest
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from apps.accounts.adapters import SocialAccountAdapter
from apps.emailauth.models import EmailIdentity
from apps.siteadmin.models import SiteInvite, SiteSettings
from apps.users.models import User


def _install_pocket_id_provider():
    """Register a provider class so connect() can attach a Pocket ID login.

    The real OpenID Connect provider is installed only when the env vars are
    set. allauth still asks the registry for ``pocket-id`` while saving the
    link. ``package`` points at a real allauth package so provider URL
    discovery does not import this test module.
    """
    from allauth.socialaccount.providers import registry
    from allauth.socialaccount.providers.base import Provider

    if registry.get_class("pocket-id") is not None:
        return

    class PocketIDProvider(Provider):
        id = "pocket-id"
        name = "Pocket ID"
        uses_apps = False
        package = "allauth.socialaccount.providers.openid_connect"

    registry.register(PocketIDProvider)


@pytest.fixture(autouse=True)
def pocket_id_social_app(db):
    """allauth looks up a SocialApp when connect() saves a Pocket ID login."""
    from django.contrib.sites.models import Site

    from allauth.socialaccount.models import SocialApp

    _install_pocket_id_provider()
    site, _ = Site.objects.get_or_create(pk=1, defaults={"domain": "example.com", "name": "example"})
    app, _ = SocialApp.objects.get_or_create(
        provider="pocket-id",
        defaults={"name": "Pocket ID", "client_id": "pocket-client", "secret": "pocket-secret", "key": ""},
    )
    app.sites.add(site)


@pytest.fixture
def request_factory(db):
    factory = RequestFactory()

    def _make():
        request = factory.get("/")
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    return _make


def _sociallogin(email="new@example.com", verified=True, uid="uid-1", extra_data=None, provider="google"):
    account = SocialAccount(provider=provider, uid=uid, extra_data=extra_data or {})
    email_addresses = [EmailAddress(email=email, verified=verified, primary=True)] if email else []
    sociallogin = SocialLogin(account=account, email_addresses=email_addresses)
    if not isinstance(getattr(sociallogin, "state", None), dict):
        sociallogin.state = {}
    return sociallogin


def _as_connect(request, user, sociallogin):
    request.user = user
    sociallogin.state["process"] = "connect"
    return sociallogin


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
def test_does_not_overwrite_existing_display_name_but_resyncs_avatar(request_factory):
    # Display name is user-editable, so it's only ever backfilled once. Avatar
    # has no user-editable alternative, so it always mirrors Google's picture.
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
    assert user.avatar_url == "https://example.com/new.jpg"


@pytest.mark.django_db
def test_new_email_blocked_when_private(request_factory):
    from allauth.core.exceptions import ImmediateHttpResponse

    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_PRIVATE)
    request = request_factory()
    sociallogin = _sociallogin(email="private@example.com", verified=True)

    with pytest.raises(ImmediateHttpResponse):
        SocialAccountAdapter().pre_social_login(request, sociallogin)

    assert not EmailIdentity.objects.filter(email="private@example.com").exists()


@pytest.mark.django_db
def test_new_email_blocked_invite_only_without_invite(request_factory):
    from allauth.core.exceptions import ImmediateHttpResponse

    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_INVITE_ONLY)
    request = request_factory()
    sociallogin = _sociallogin(email="uninvited@example.com", verified=True)

    with pytest.raises(ImmediateHttpResponse):
        SocialAccountAdapter().pre_social_login(request, sociallogin)

    assert not EmailIdentity.objects.filter(email="uninvited@example.com").exists()


@pytest.mark.django_db
def test_new_email_allowed_invite_only_with_valid_invite(request_factory):
    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_INVITE_ONLY)
    invite = SiteInvite.generate("invited@example.com", invited_by=None)
    request = request_factory()
    sociallogin = _sociallogin(email="invited@example.com", verified=True)

    SocialAccountAdapter().pre_social_login(request, sociallogin)

    assert EmailIdentity.objects.filter(email="invited@example.com").exists()
    invite.refresh_from_db()
    assert invite.accepted_at is not None


@pytest.mark.django_db
def test_repeat_login_skips_identity_work(request_factory, django_assert_num_queries):
    user = User.objects.create_user(display_name="Existing Name")
    account = SocialAccount(provider="google", uid="uid-existing", user=user)
    sociallogin = SocialLogin(user=user, account=account)
    request = request_factory()

    with django_assert_num_queries(1):
        # is_existing issues one query (checking the user still exists); no
        # avatar/name sync work runs since extra_data has nothing to sync.
        SocialAccountAdapter().pre_social_login(request, sociallogin)


@pytest.mark.django_db
def test_repeat_login_refreshes_avatar_from_google(request_factory):
    user = User.objects.create_user(
        display_name="Existing Name", avatar_url="https://example.com/old.jpg"
    )
    account = SocialAccount(
        provider="google",
        uid="uid-existing",
        user=user,
        extra_data={"name": "New Name", "picture": "https://example.com/new.jpg"},
    )
    sociallogin = SocialLogin(user=user, account=account)
    request = request_factory()

    SocialAccountAdapter().pre_social_login(request, sociallogin)

    user.refresh_from_db()
    assert user.avatar_url == "https://example.com/new.jpg"
    assert user.display_name == "Existing Name"


def _pocket_claims(**extra):
    claims = {"email_verified": True, "email": "ada@example.com"}
    claims.update(extra)
    return claims


@pytest.mark.django_db
def test_pocket_id_first_login_links_existing_google_account(request_factory):
    from apps.tasks.models import Task

    user = User.objects.create_user()
    EmailIdentity.objects.create(user=user, email="ada@example.com", verified=True)
    SocialAccount.objects.create(user=user, provider="google", uid="google-sub")
    task = Task.objects.create(user=user, title="Keep me")
    sociallogin = _sociallogin(
        provider="pocket-id",
        email="Ada@example.com",
        verified=True,
        uid="pocket-sub",
        extra_data=_pocket_claims(name="Ada Lovelace", picture="https://id.example/ada.png"),
    )

    SocialAccountAdapter().pre_social_login(request_factory(), sociallogin)

    assert User.objects.count() == 1
    assert sociallogin.user.id == user.id
    assert SocialAccount.objects.get(provider="pocket-id", uid="pocket-sub").user_id == user.id
    task.refresh_from_db()
    assert task.user_id == user.id
    assert EmailIdentity.objects.filter(email="ada@example.com").count() == 1


@pytest.mark.django_db
def test_pocket_id_unverified_email_is_refused(request_factory):
    from allauth.core.exceptions import ImmediateHttpResponse

    sociallogin = _sociallogin(
        provider="pocket-id",
        email="unverified@example.com",
        verified=False,
        extra_data={"email": "unverified@example.com", "email_verified": False},
    )

    with pytest.raises(ImmediateHttpResponse):
        SocialAccountAdapter().pre_social_login(request_factory(), sociallogin)

    assert not EmailIdentity.objects.filter(email="unverified@example.com").exists()
    assert User.objects.count() == 0


@pytest.mark.django_db
def test_pocket_id_refuses_when_claim_says_unverified(request_factory):
    from allauth.core.exceptions import ImmediateHttpResponse

    # allauth may have marked the address verified; an explicit OIDC false still refuses.
    sociallogin = _sociallogin(
        provider="pocket-id",
        email="unverified@example.com",
        verified=True,
        extra_data={"email": "unverified@example.com", "email_verified": False},
    )

    with pytest.raises(ImmediateHttpResponse):
        SocialAccountAdapter().pre_social_login(request_factory(), sociallogin)

    assert not EmailIdentity.objects.filter(email="unverified@example.com").exists()


@pytest.mark.django_db
def test_pocket_id_new_email_blocked_when_private(request_factory):
    from allauth.core.exceptions import ImmediateHttpResponse

    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_PRIVATE)
    sociallogin = _sociallogin(
        provider="pocket-id",
        email="private@example.com",
        verified=True,
        extra_data={"email": "private@example.com", "email_verified": True},
    )

    with pytest.raises(ImmediateHttpResponse):
        SocialAccountAdapter().pre_social_login(request_factory(), sociallogin)

    assert not EmailIdentity.objects.filter(email="private@example.com").exists()


@pytest.mark.django_db
def test_pocket_id_new_email_blocked_invite_only_without_invite(request_factory):
    from allauth.core.exceptions import ImmediateHttpResponse

    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_INVITE_ONLY)
    sociallogin = _sociallogin(
        provider="pocket-id",
        email="uninvited@example.com",
        verified=True,
        extra_data={"email": "uninvited@example.com", "email_verified": True},
    )

    with pytest.raises(ImmediateHttpResponse):
        SocialAccountAdapter().pre_social_login(request_factory(), sociallogin)

    assert not EmailIdentity.objects.filter(email="uninvited@example.com").exists()


@pytest.mark.django_db
def test_pocket_id_new_email_allowed_invite_only_with_valid_invite(request_factory):
    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_INVITE_ONLY)
    invite = SiteInvite.generate("invited@example.com", invited_by=None)
    sociallogin = _sociallogin(
        provider="pocket-id",
        email="invited@example.com",
        verified=True,
        extra_data={"email": "invited@example.com", "email_verified": True, "name": "Invited Person"},
    )

    SocialAccountAdapter().pre_social_login(request_factory(), sociallogin)

    identity = EmailIdentity.objects.get(email="invited@example.com")
    assert sociallogin.user.id == identity.user_id
    assert User.objects.count() == 1
    invite.refresh_from_db()
    assert invite.accepted_at is not None


@pytest.mark.django_db
def test_pocket_id_backfills_name_from_oidc_claims(request_factory):
    sociallogin = _sociallogin(
        provider="pocket-id",
        email="oidc@example.com",
        verified=True,
        extra_data={
            "email": "oidc@example.com",
            "email_verified": True,
            "given_name": "Ada",
            "family_name": "Lovelace",
            "picture": "https://id.example/ada.png",
        },
    )

    SocialAccountAdapter().pre_social_login(request_factory(), sociallogin)

    user = EmailIdentity.objects.get(email="oidc@example.com").user
    assert user.display_name == "Ada Lovelace"
    assert user.avatar_url == "https://id.example/ada.png"


@pytest.mark.django_db
def test_connect_pocket_id_links_the_signed_in_user(request_factory):
    from apps.tasks.models import Task

    user = User.objects.create_user()
    EmailIdentity.objects.create(user=user, email="ada@example.com", verified=True)
    task = Task.objects.create(user=user, title="Stay")
    request = request_factory()
    sociallogin = _as_connect(
        request,
        user,
        _sociallogin(
            provider="pocket-id",
            email="ada@example.com",
            verified=True,
            uid="pocket-sub",
            extra_data=_pocket_claims(name="Ada", picture="https://id.example/a.png"),
        ),
    )

    SocialAccountAdapter().pre_social_login(request, sociallogin)

    assert sociallogin.user.id == user.id
    assert SocialAccount.objects.get(provider="pocket-id", uid="pocket-sub").user_id == user.id
    assert User.objects.count() == 1
    task.refresh_from_db()
    assert task.user_id == user.id
    assert EmailIdentity.objects.get(email="ada@example.com").user_id == user.id


@pytest.mark.django_db
def test_connect_pocket_id_adds_a_new_email_to_the_current_user(request_factory):
    user = User.objects.create_user()
    request = request_factory()
    sociallogin = _as_connect(
        request,
        user,
        _sociallogin(
            provider="pocket-id",
            email="person@example.com",
            verified=True,
            uid="pocket-new",
            extra_data={"email": "person@example.com", "email_verified": True},
        ),
    )

    SocialAccountAdapter().pre_social_login(request, sociallogin)

    assert sociallogin.user.id == user.id
    assert EmailIdentity.objects.get(email="person@example.com").user_id == user.id
    assert User.objects.count() == 1


@pytest.mark.django_db
def test_connect_pocket_id_is_not_blocked_by_the_private_signup_gate(request_factory):
    SiteSettings.objects.create(pk=1, signup_mode=SiteSettings.MODE_PRIVATE)
    user = User.objects.create_user()
    request = request_factory()
    sociallogin = _as_connect(
        request,
        user,
        _sociallogin(
            provider="pocket-id",
            email="person@example.com",
            verified=True,
            uid="pocket-new",
            extra_data={"email": "person@example.com", "email_verified": True},
        ),
    )

    SocialAccountAdapter().pre_social_login(request, sociallogin)

    assert EmailIdentity.objects.get(email="person@example.com").user_id == user.id


@pytest.mark.django_db
def test_connect_refuses_pocket_id_identity_owned_by_another_user(request_factory):
    from allauth.core.exceptions import ImmediateHttpResponse

    owner = User.objects.create_user(display_name="Owner", avatar_url="https://example.com/owner.png")
    current = User.objects.create_user()
    SocialAccount.objects.create(
        user=owner,
        provider="pocket-id",
        uid="pocket-sub",
        extra_data={"picture": "https://example.com/owner.png"},
    )
    request = request_factory()
    sociallogin = _as_connect(
        request,
        current,
        _sociallogin(
            provider="pocket-id",
            email="ada@example.com",
            verified=True,
            uid="pocket-sub",
            extra_data=_pocket_claims(picture="https://example.com/stolen.png", name="Stolen"),
        ),
    )

    with pytest.raises(ImmediateHttpResponse) as exc_info:
        SocialAccountAdapter().pre_social_login(request, sociallogin)

    assert exc_info.value.response["Location"] == "/settings/"
    assert SocialAccount.objects.get(provider="pocket-id", uid="pocket-sub").user_id == owner.id
    assert not SocialAccount.objects.filter(user=current, provider="pocket-id").exists()
    assert User.objects.count() == 2
    owner.refresh_from_db()
    assert owner.avatar_url == "https://example.com/owner.png"


@pytest.mark.django_db
def test_connect_refuses_email_owned_by_another_user(request_factory):
    from allauth.core.exceptions import ImmediateHttpResponse

    owner = User.objects.create_user()
    EmailIdentity.objects.create(user=owner, email="ada@example.com", verified=True)
    current = User.objects.create_user()
    request = request_factory()
    sociallogin = _as_connect(
        request,
        current,
        _sociallogin(
            provider="pocket-id",
            email="ada@example.com",
            verified=True,
            uid="pocket-new",
            extra_data=_pocket_claims(),
        ),
    )

    with pytest.raises(ImmediateHttpResponse):
        SocialAccountAdapter().pre_social_login(request, sociallogin)

    assert EmailIdentity.objects.get(email="ada@example.com").user_id == owner.id
    assert User.objects.count() == 2
    assert not SocialAccount.objects.filter(user=current).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "provider,extra_data",
    [
        ("google", {"name": "New Name", "picture": "https://example.com/g.jpg"}),
        (
            "pocket-id",
            {
                "name": "New Name",
                "picture": "https://example.com/p.jpg",
                "email": "ada@example.com",
                "email_verified": True,
            },
        ),
    ],
)
def test_repeat_login_resyncs_profile_for_google_and_pocket_id(request_factory, provider, extra_data):
    user = User.objects.create_user(display_name="Existing Name", avatar_url="https://example.com/old.jpg")
    account = SocialAccount(provider=provider, uid=f"{provider}-uid", user=user, extra_data=extra_data)
    sociallogin = SocialLogin(user=user, account=account)

    SocialAccountAdapter().pre_social_login(request_factory(), sociallogin)

    user.refresh_from_db()
    assert user.avatar_url == extra_data["picture"]
    assert user.display_name == "Existing Name"


@pytest.mark.django_db
def test_connect_redirects_back_to_settings():
    from django.urls import reverse

    assert SocialAccountAdapter().get_connect_redirect_url(None, None) == reverse("users:settings")
