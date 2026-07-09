from django.conf import settings as django_settings
from django.contrib.auth import logout
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from .utils import safe_next_url


class LoginView(View):
    """Combined login page — Email OTP and OAuth provider tabs."""

    def get(self, request):
        next_url = safe_next_url(request, request.GET.get("next"))
        if request.user.is_authenticated:
            return redirect(next_url or django_settings.LOGIN_REDIRECT_URL)
        return render(request, "login.html", {"next": next_url})


class LogoutView(View):
    def post(self, request):
        logout(request)
        return redirect(reverse("accounts:login"))
