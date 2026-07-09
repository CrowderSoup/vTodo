import uuid

from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Routes OAuth logins through the same EmailIdentity model email-OTP uses,
    so a verified email matches the same account regardless of login method.
    """

    def pre_social_login(self, request, sociallogin):
        if sociallogin.is_existing:
            return  # repeat login, already linked — nothing to do

        verified_email = next(
            (e.email for e in sociallogin.email_addresses if e.verified), None
        )
        if not verified_email:
            messages.error(request, "Your account's email isn't verified.")
            raise ImmediateHttpResponse(redirect(reverse("accounts:login")))

        from apps.emailauth.models import EmailIdentity
        from apps.users.models import User

        try:
            identity = EmailIdentity.objects.select_related("user").get(email=verified_email)
        except EmailIdentity.DoesNotExist:
            user = User.objects.create_user(username=uuid.uuid4().hex[:16])
            identity = EmailIdentity.objects.create(user=user, email=verified_email, verified=True)
        else:
            if not identity.verified:
                identity.verified = True
                identity.save(update_fields=["verified"])

        user = identity.user
        extra_data = sociallogin.account.extra_data
        update_fields = []
        if not user.display_name and extra_data.get("name"):
            user.display_name = extra_data["name"]
            update_fields.append("display_name")
        if not user.avatar_url and extra_data.get("picture"):
            user.avatar_url = extra_data["picture"]
            update_fields.append("avatar_url")
        if update_fields:
            user.save(update_fields=update_fields)

        sociallogin.connect(request, user)
