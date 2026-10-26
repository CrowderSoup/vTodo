"""Match a verified Google account the same way the website login does.

The website (apps.accounts.adapters.SocialAccountAdapter) and the Android
app's ID-token exchange both end up here, so a person who already signed in
on one gets the same user on the other.
"""

import uuid

from django.conf import settings
from google.auth.exceptions import GoogleAuthError, TransportError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from apps.emailauth.models import EmailIdentity
from apps.siteadmin.selectors import consume_signup_slot
from apps.users.models import User

_GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


class GoogleSignInError(Exception):
    """A sign-in failure whose message is safe to show the person."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class GoogleSignInNotConfigured(GoogleSignInError):
    pass


class GoogleUnavailable(GoogleSignInError):
    pass


class InvalidGoogleIdToken(GoogleSignInError):
    pass


class UnverifiedGoogleEmail(GoogleSignInError):
    pass


class SignupClosed(GoogleSignInError):
    pass


class AccountDisabled(GoogleSignInError):
    pass


def verify_google_id_token(raw_token: str) -> dict:
    """Check a Google ID token's signature, audience, issuer, and expiry.

    The audience is the web OAuth client (GOOGLE_CLIENT_ID). An Android
    client in the same Google Cloud project asks Google for a token aimed
    at that audience; the client secret never leaves the server.
    """
    client_id = settings.GOOGLE_CLIENT_ID
    if not client_id:
        raise GoogleSignInNotConfigured("Google sign-in is not configured on this server.")
    if not isinstance(raw_token, str) or not raw_token.strip():
        raise InvalidGoogleIdToken("Google didn't accept that sign-in. Try again.")
    try:
        claims = id_token.verify_oauth2_token(
            raw_token.strip(),
            google_requests.Request(),
            client_id,
        )
    except TransportError as exc:
        raise GoogleUnavailable("Couldn't reach Google to check that sign-in.") from exc
    except (ValueError, GoogleAuthError) as exc:
        raise InvalidGoogleIdToken("Google didn't accept that sign-in. Try again.") from exc

    if claims.get("iss") not in _GOOGLE_ISSUERS:
        raise InvalidGoogleIdToken("Google didn't accept that sign-in. Try again.")
    audience = claims.get("aud")
    if audience != client_id and not (isinstance(audience, list) and client_id in audience):
        raise InvalidGoogleIdToken("Google didn't accept that sign-in. Try again.")
    return claims


def account_for_verified_google_email(email: str, extra_data: dict | None = None) -> User:
    """Find or create the user for a verified Google email address."""
    address = (email or "").strip().lower()
    if not address or "@" not in address:
        raise UnverifiedGoogleEmail("Your account's email isn't verified.")

    identity = EmailIdentity.objects.select_related("user").filter(email__iexact=address).first()
    if identity is None:
        if not consume_signup_slot(address):
            raise SignupClosed("vtodo isn't open for signups right now.")
        user = User.objects.create_user(username=uuid.uuid4().hex[:16])
        # EmailIdentity emails are stored lower-cased (see ADMIN_EMAILS).
        identity = EmailIdentity.objects.create(user=user, email=address, verified=True)
    else:
        if not identity.verified:
            identity.verified = True
            identity.save(update_fields=["verified"])
        user = identity.user

    sync_google_profile(user, extra_data or {})
    return user


def sync_google_profile(user, extra_data):
    """Display name is backfilled once and left to the user to edit from
    then on. Avatar has no user-editable alternative, so it always mirrors
    Google's current picture."""
    if not extra_data:
        return
    update_fields = []
    name = extra_data.get("name") or ""
    if not isinstance(name, str):
        name = ""
    name = name.strip()[:255]
    if not user.display_name and name:
        user.display_name = name
        update_fields.append("display_name")
    picture = extra_data.get("picture") or ""
    if not isinstance(picture, str):
        picture = ""
    picture = picture.strip()[:2000]
    if picture and user.avatar_url != picture:
        user.avatar_url = picture
        update_fields.append("avatar_url")
    if update_fields:
        user.save(update_fields=update_fields)


def sign_in_with_google_id_token(raw_token: str, device_name: str = "") -> str:
    """Verify the ID token and return a new API token for this device.

    Each sign-in gets its own DeviceToken, so the phone can revoke it on
    sign-out and Settings can revoke a lost phone without touching the
    Settings → API token. It is not an OAuth access token and it is not
    minted through django-oauth-toolkit.
    """
    from apps.api.models import DeviceToken

    claims = verify_google_id_token(raw_token)
    verified = claims.get("email_verified")
    if verified not in (True, "true"):
        raise UnverifiedGoogleEmail("Your account's email isn't verified.")
    email = claims.get("email")
    if not isinstance(email, str):
        email = ""
    user = account_for_verified_google_email(
        email,
        {"name": claims.get("name") or "", "picture": claims.get("picture") or ""},
    )
    if not user.is_active:
        raise AccountDisabled("This account is disabled.")
    _, key = DeviceToken.issue(user, device_name.strip())
    return key
