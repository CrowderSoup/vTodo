from django.conf import settings as django_settings
from django.contrib.auth import logout
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from apps.accounts.pocket_id import pocket_id_login_url

from .utils import safe_next_url


class LoginView(View):
    """Login page. Google is always offered. Pocket ID appears when configured."""

    def get(self, request):
        next_url = safe_next_url(request, request.GET.get("next"))
        if request.user.is_authenticated:
            return redirect(next_url or django_settings.LOGIN_REDIRECT_URL)
        return render(
            request,
            "login.html",
            {"next": next_url, "pocket_id_login_url": pocket_id_login_url(next_url)},
        )


class LogoutView(View):
    def post(self, request):
        logout(request)
        return redirect(reverse("accounts:login"))
