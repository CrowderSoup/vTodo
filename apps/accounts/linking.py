"""Match a verified sign-in email to one existing user row.

Google (the website and the Android ID-token exchange) and Pocket ID both
come through here. The caller attaches the new social login to that user.
Nothing in this module merges two users or creates a second user for an
email that already has an EmailIdentity.
"""

import uuid

from allauth.socialaccount.models import SocialAccount

from apps.emailauth.models import EmailIdentity
from apps.siteadmin.selectors import consume_signup_slot
from apps.users.models import User

_VERIFIED_FLAGS = (True, "true", "True", 1, "1")
_PROVIDER_LABELS = {
    "google": "Google",
    "pocket-id": "Pocket ID",
}
_PROVIDER_ORDER = {"google": 0, "pocket-id": 1}


class AccountLinkError(Exception):
    """A sign-in failure whose message is safe to show the person."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class SignupNotAllowed(AccountLinkError):
    pass


def account_for_verified_email(email: str, extra_data: dict | None = None) -> User:
    """Find or create the single user for a verified sign-in email."""
    address = (email or "").strip().lower()
    if not address or "@" not in address:
        raise AccountLinkError("Your account's email isn't verified.")

    identity = EmailIdentity.objects.select_related("user").filter(email__iexact=address).first()
    if identity is None:
        if not consume_signup_slot(address):
            raise SignupNotAllowed("vtodo isn't open for signups right now.")
        user = User.objects.create_user(username=uuid.uuid4().hex[:16])
        # EmailIdentity emails are stored lower-cased (see ADMIN_EMAILS).
        EmailIdentity.objects.create(user=user, email=address, verified=True)
    else:
        if not identity.verified:
            identity.verified = True
            identity.save(update_fields=["verified"])
        user = identity.user

    sync_social_profile(user, extra_data or {})
    return user


def sync_social_profile(user, extra_data):
    """Display name is backfilled once and left for the user to edit.

    Avatar has no user-editable alternative, so it always mirrors the
    provider's current picture. Google sends ``name`` and ``picture``.
    Pocket ID sends those OIDC claims, or ``given_name`` / ``family_name``
    / ``preferred_username`` when ``name`` is absent.
    """
    if not extra_data:
        return
    update_fields = []
    name = _display_name(extra_data)
    if not user.display_name and name:
        user.display_name = name
        update_fields.append("display_name")
    picture = _picture(extra_data)
    if picture and user.avatar_url != picture:
        user.avatar_url = picture
        update_fields.append("avatar_url")
    if update_fields:
        user.save(update_fields=update_fields)


def claims_mark_email_unverified(extra_data) -> bool:
    """True when provider claims explicitly say the email is not verified.

    A missing flag is not a refusal: allauth has already copied a verified
    address onto the social login, and older Google payloads only set
    ``verified_email`` when it is true. An explicit false from either
    Google (``verified_email``) or OIDC (``email_verified``) is a refusal.
    """
    if not extra_data:
        return False
    for key in ("email_verified", "verified_email"):
        if key in extra_data and extra_data[key] not in _VERIFIED_FLAGS:
            return True
    return False


def provider_label(provider: str) -> str:
    return _PROVIDER_LABELS.get(provider, provider)


def list_connected_accounts(user):
    seen = []
    for provider in SocialAccount.objects.filter(user=user).order_by("id").values_list("provider", flat=True):
        if provider not in seen:
            seen.append(provider)
    seen.sort(key=lambda provider: (_PROVIDER_ORDER.get(provider, 9), provider))
    return [{"provider": provider, "label": provider_label(provider)} for provider in seen]


def signed_in_provider_label(accounts) -> str:
    providers = {account["provider"] for account in accounts}
    if "pocket-id" in providers and "google" not in providers:
        return "Pocket ID"
    if "google" in providers or not providers:
        return "Google"
    return accounts[0]["label"]


def settings_connection_context(user) -> dict:
    from apps.accounts.pocket_id import POCKET_ID_PROVIDER_ID, pocket_id_login_url

    accounts = list_connected_accounts(user)
    linked = {account["provider"] for account in accounts}
    connect_url = ""
    if POCKET_ID_PROVIDER_ID not in linked:
        connect_url = pocket_id_login_url(next_url="/settings/", process="connect")
    return {
        "social_accounts": accounts,
        "signed_in_provider": signed_in_provider_label(accounts),
        "pocket_id_connect_url": connect_url,
    }


def _as_text(value) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _display_name(extra_data) -> str:
    name = _as_text(extra_data.get("name"))
    if not name:
        given = _as_text(extra_data.get("given_name"))
        family = _as_text(extra_data.get("family_name"))
        name = f"{given} {family}".strip()
    if not name:
        name = _as_text(extra_data.get("preferred_username"))
    return name[:255]


def _picture(extra_data) -> str:
    return _as_text(extra_data.get("picture"))[:2000]
