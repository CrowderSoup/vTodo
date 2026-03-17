import secrets
import uuid

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from .auth import (
    build_authorization_url,
    discover_endpoints,
    exchange_code_for_token,
    generate_pkce_pair,
)
from .models import IndieAuthIdentity


class LoginView(View):
    """Combined login page with IndieAuth and Email OTP tabs."""

    def get(self, request):
        if request.user.is_authenticated:
            return redirect(django_settings.LOGIN_REDIRECT_URL)
        return render(request, "login.html")


class StartView(View):
    """Kick off the IndieAuth PKCE flow."""

    def post(self, request):
        me = request.POST.get("me", "").strip()
        if not me:
            messages.error(request, "Please enter your website URL.")
            return redirect(reverse("indieauth:login"))

        try:
            endpoints = discover_endpoints(me)
        except ValueError as exc:
            messages.error(request, f"Could not reach your website: {exc}")
            return redirect(reverse("indieauth:login"))

        auth_endpoint = endpoints.get("authorization_endpoint")
        if not auth_endpoint:
            messages.error(
                request,
                "No IndieAuth authorization endpoint found at that URL. "
                "Make sure your site has a <link rel=\"authorization_endpoint\"> tag.",
            )
            return redirect(reverse("indieauth:login"))

        token_endpoint = endpoints.get("token_endpoint", "")
        if not token_endpoint:
            messages.error(request, "No token endpoint found at that URL.")
            return redirect(reverse("indieauth:login"))

        verifier, challenge = generate_pkce_pair()
        state = secrets.token_urlsafe(16)

        request.session["ia_verifier"] = verifier
        request.session["ia_state"] = state
        request.session["ia_me"] = me
        request.session["ia_token_endpoint"] = token_endpoint
        request.session["ia_micropub_endpoint"] = endpoints.get("micropub") or ""

        redirect_uri = request.build_absolute_uri(reverse("indieauth:callback"))
        client_id = getattr(
            django_settings,
            "INDIEAUTH_CLIENT_ID",
            request.build_absolute_uri("/"),
        )

        auth_url = build_authorization_url(
            auth_endpoint, me, redirect_uri, state, client_id, challenge
        )
        return redirect(auth_url)


class CallbackView(View):
    """Handle the IndieAuth authorization callback."""

    def get(self, request):
        error = request.GET.get("error")
        if error:
            desc = request.GET.get("error_description", error)
            messages.error(request, f"Authorization failed: {desc}")
            return redirect(reverse("indieauth:login"))

        state = request.GET.get("state", "")
        session_state = request.session.get("ia_state", "")
        if not state or state != session_state:
            messages.error(request, "Invalid state parameter. Please try again.")
            return redirect(reverse("indieauth:login"))

        code = request.GET.get("code", "")
        verifier = request.session.get("ia_verifier", "")
        token_endpoint = request.session.get("ia_token_endpoint", "")
        session_micropub_endpoint = request.session.get("ia_micropub_endpoint", "")
        session_me = request.session.get("ia_me", "")

        redirect_uri = request.build_absolute_uri(reverse("indieauth:callback"))
        client_id = getattr(
            django_settings,
            "INDIEAUTH_CLIENT_ID",
            request.build_absolute_uri("/"),
        )

        try:
            token_data = exchange_code_for_token(
                token_endpoint, code, redirect_uri, client_id, verifier
            )
        except ValueError as exc:
            messages.error(request, f"Login failed: {exc}")
            return redirect(reverse("indieauth:login"))

        # Clean up session keys
        for key in ("ia_verifier", "ia_state", "ia_me", "ia_token_endpoint", "ia_micropub_endpoint"):
            request.session.pop(key, None)

        me = token_data.get("me") or session_me
        access_token = token_data.get("access_token", "")
        micropub_endpoint = token_data.get("micropub") or session_micropub_endpoint

        # Get or create identity + user
        from apps.users.models import User

        try:
            identity = IndieAuthIdentity.objects.select_related("user").get(me=me)
        except IndieAuthIdentity.DoesNotExist:
            user = User.objects.create_user(username=uuid.uuid4().hex[:16])
            identity = IndieAuthIdentity.objects.create(user=user, me=me)

        # Update micropub config on the user
        user = identity.user
        if micropub_endpoint and access_token:
            user.micropub_endpoint = micropub_endpoint
            user.micropub_token = access_token
            user.save(update_fields=["micropub_endpoint", "micropub_token"])

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect(reverse("boards:board"))


class LogoutView(View):
    def post(self, request):
        logout(request)
        return redirect(reverse("indieauth:login"))
