import uuid

from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Matches an OAuth login to an existing account by verified email via
    EmailIdentity, so team invites and admin-email checks work the same
    way regardless of when the account was first created.
    """

    def pre_social_login(self, request, sociallogin):
        if sociallogin.is_existing:
            # Repeat login: no new identity work needed, but re-sync the cached
            # profile fields in case the user changed their name/photo on Google.
            self._sync_google_profile(sociallogin.user, sociallogin.account.extra_data)
            return

        verified_email = next(
            (e.email for e in sociallogin.email_addresses if e.verified), None
        )
        if not verified_email:
            messages.error(request, "Your account's email isn't verified.")
            raise ImmediateHttpResponse(redirect(reverse("accounts:login")))

        from apps.emailauth.models import EmailIdentity
        from apps.siteadmin.selectors import consume_signup_slot
        from apps.users.models import User

        try:
            identity = EmailIdentity.objects.select_related("user").get(email=verified_email)
        except EmailIdentity.DoesNotExist:
            if not consume_signup_slot(verified_email):
                messages.error(request, "vtodo isn't open for signups right now.")
                raise ImmediateHttpResponse(redirect(reverse("accounts:login")))

            user = User.objects.create_user(username=uuid.uuid4().hex[:16])
            identity = EmailIdentity.objects.create(user=user, email=verified_email, verified=True)
        else:
            if not identity.verified:
                identity.verified = True
                identity.save(update_fields=["verified"])

        user = identity.user
        self._sync_google_profile(user, sociallogin.account.extra_data)

        sociallogin.connect(request, user)

    @staticmethod
    def _sync_google_profile(user, extra_data):
        """Display name is backfilled once and left to the user to edit from
        then on. Avatar has no user-editable alternative, so it always mirrors
        Google's current picture."""
        update_fields = []
        if not user.display_name and extra_data.get("name"):
            user.display_name = extra_data["name"]
            update_fields.append("display_name")
        picture = extra_data.get("picture", "")
        if picture and user.avatar_url != picture:
            user.avatar_url = picture
            update_fields.append("avatar_url")
        if update_fields:
            user.save(update_fields=update_fields)
