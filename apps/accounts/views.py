from django.conf import settings as django_settings
from django.contrib.auth import logout
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View


class LoginView(View):
    """Combined login page — Email OTP and OAuth provider tabs."""

    def get(self, request):
        if request.user.is_authenticated:
            return redirect(django_settings.LOGIN_REDIRECT_URL)
        return render(request, "login.html")


class LogoutView(View):
    def post(self, request):
        logout(request)
        return redirect(reverse("accounts:login"))
