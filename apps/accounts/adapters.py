from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from apps.accounts.google_accounts import GoogleSignInError, account_for_verified_google_email, sync_google_profile


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Matches an OAuth login to an existing account by verified email via
    EmailIdentity, so admin-email checks work the same
    way regardless of when the account was first created.
    """

    def pre_social_login(self, request, sociallogin):
        if sociallogin.is_existing:
            # Repeat login: no new identity work needed, but re-sync the cached
            # profile fields in case the user changed their name/photo on Google.
            sync_google_profile(sociallogin.user, sociallogin.account.extra_data)
            return

        verified_email = next(
            (e.email for e in sociallogin.email_addresses if e.verified), None
        )
        if not verified_email:
            messages.error(request, "Your account's email isn't verified.")
            raise ImmediateHttpResponse(redirect(reverse("accounts:login")))

        try:
            user = account_for_verified_google_email(verified_email, sociallogin.account.extra_data)
        except GoogleSignInError as exc:
            messages.error(request, exc.message)
            raise ImmediateHttpResponse(redirect(reverse("accounts:login")))

        sociallogin.connect(request, user)
