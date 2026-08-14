from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.cache import cache
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from apps.users.selectors import is_admin

from .models import SiteInvite, SiteSettings

INVITE_RATE_LIMIT = 5
INVITE_RATE_WINDOW = 3600  # seconds (1 hour)


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return is_admin(self.request.user)


class DashboardView(AdminRequiredMixin, View):
    def get(self, request):
        site_settings = SiteSettings.load()
        pending_invites = [inv for inv in SiteInvite.objects.all() if inv.is_valid]
        context = {
            "site_settings": site_settings,
            "mode_choices": SiteSettings.MODE_CHOICES,
            "pending_invites": pending_invites,
            "active_tab": "signups",
        }
        return render(request, "siteadmin/dashboard.html", context)


class SignupModeUpdateView(AdminRequiredMixin, View):
    def post(self, request):
        mode = request.POST.get("signup_mode", "").strip()
        valid_modes = {choice for choice, _ in SiteSettings.MODE_CHOICES}
        if mode not in valid_modes:
            messages.error(request, "Not a valid signup mode.")
            return redirect(reverse("siteadmin:dashboard"))

        site_settings = SiteSettings.load()
        site_settings.signup_mode = mode
        site_settings.save(update_fields=["signup_mode"])
        messages.success(request, "Signup mode updated.")
        return redirect(reverse("siteadmin:dashboard"))


class SiteInviteCreateView(AdminRequiredMixin, View):
    def post(self, request):
        email = request.POST.get("email", "").strip().lower()
        if not email:
            messages.error(request, "Enter an email address to invite.")
            return redirect(reverse("siteadmin:dashboard"))

        rate_key = f"site_invite_rate:{email}"
        count = cache.get(rate_key, 0)
        if count >= INVITE_RATE_LIMIT:
            messages.error(request, "Too many invites sent to that address. Try again later.")
            return redirect(reverse("siteadmin:dashboard"))

        invite = SiteInvite.generate(email, request.user)

        try:
            send_mail(
                subject="You've been invited to vtodo",
                message=(
                    f"{request.user.display_name or request.user.username} invited you to join vtodo.\n\n"
                    f"Log in at {request.build_absolute_uri(reverse('accounts:login'))} with this email "
                    "address to create your account.\n\n"
                    "This invite expires in 7 days."
                ),
                from_email=None,
                recipient_list=[email],
                fail_silently=False,
            )
        except Exception:
            messages.error(request, "Failed to send invite email. Please try again later.")
            return redirect(reverse("siteadmin:dashboard"))

        cache.set(rate_key, count + 1, INVITE_RATE_WINDOW)
        messages.success(request, f"Invited {email}.")
        return redirect(reverse("siteadmin:dashboard"))
