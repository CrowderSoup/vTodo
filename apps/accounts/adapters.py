from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialAccount
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from apps.accounts.linking import (
    AccountLinkError,
    account_for_verified_email,
    claims_mark_email_unverified,
    sync_social_profile,
)
from apps.emailauth.models import EmailIdentity


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Matches a social login to an existing account by verified email via
    EmailIdentity. Google and Pocket ID both use this path, so a first
    Pocket ID login lands on the same user row as a Google account with
    that email. Settings uses allauth's connect flow to attach a new
    login to the signed-in user. An identity already linked to someone
    else is refused. Two user rows are never merged.
    """

    def get_connect_redirect_url(self, request, socialaccount):
        return reverse("users:settings")

    def pre_social_login(self, request, sociallogin):
        if sociallogin.is_existing:
            if _connect_targets_other_user(request, sociallogin):
                _refuse(request, sociallogin, "That sign-in is already linked to a different account.")
            # Repeat login: no new identity work, but re-sync the cached
            # profile in case the name or photo changed at the provider.
            sync_social_profile(sociallogin.user, sociallogin.account.extra_data)
            return

        if _is_connect(request, sociallogin) and _identity_owned_by_someone_else(sociallogin, request.user):
            _refuse(request, sociallogin, "That sign-in is already linked to a different account.")

        verified_email = _verified_email(sociallogin)
        if not verified_email:
            _refuse(request, sociallogin, "Your account's email isn't verified.")

        if _is_connect(request, sociallogin):
            _connect_current_user(request, sociallogin, verified_email)
            return

        try:
            user = account_for_verified_email(verified_email, sociallogin.account.extra_data)
        except AccountLinkError as exc:
            _refuse(request, sociallogin, exc.message)

        sociallogin.connect(request, user)


def _verified_email(sociallogin):
    extra = sociallogin.account.extra_data or {}
    if claims_mark_email_unverified(extra):
        return None
    return next((email.email for email in sociallogin.email_addresses if email.verified and email.email), None)


def _process(sociallogin) -> str:
    state = getattr(sociallogin, "state", None)
    if isinstance(state, dict):
        return str(state.get("process") or "")
    return ""


def _is_connect(request, sociallogin) -> bool:
    if _process(sociallogin) != "connect":
        return False
    user = getattr(request, "user", None)
    return bool(user and getattr(user, "is_authenticated", False))


def _connect_targets_other_user(request, sociallogin) -> bool:
    # Called only after is_existing, which already queried. Don't touch
    # sociallogin.user unless this is an explicit connect, or a repeat
    # login picks up a second query.
    if not _is_connect(request, sociallogin):
        return False
    return sociallogin.user.pk != request.user.pk


def _identity_owned_by_someone_else(sociallogin, user) -> bool:
    return (
        SocialAccount.objects.filter(
            provider=sociallogin.account.provider,
            uid=sociallogin.account.uid,
        )
        .exclude(user=user)
        .exists()
    )


def _connect_current_user(request, sociallogin, verified_email):
    user = request.user
    address = verified_email.strip().lower()
    identity = EmailIdentity.objects.filter(email__iexact=address).first()
    if identity is not None and identity.user_id != user.id:
        _refuse(request, sociallogin, "That email already belongs to a different account.")
    if identity is None:
        EmailIdentity.objects.create(user=user, email=address, verified=True)
    elif not identity.verified:
        identity.verified = True
        identity.save(update_fields=["verified"])
    sync_social_profile(user, sociallogin.account.extra_data)
    sociallogin.connect(request, user)


def _refuse(request, sociallogin, message):
    messages.error(request, message)
    if _is_connect(request, sociallogin):
        target = reverse("users:settings")
    else:
        target = reverse("accounts:login")
    raise ImmediateHttpResponse(redirect(target))
