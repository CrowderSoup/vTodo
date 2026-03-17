import uuid

from django.contrib import messages
from django.contrib.auth import login
from django.core.cache import cache
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from .models import EmailIdentity, EmailOTP

OTP_RATE_LIMIT = 3
OTP_RATE_WINDOW = 3600  # seconds (1 hour)


class RequestOTPView(View):
    """Accept email address, send OTP code, redirect to verify screen."""

    def post(self, request):
        email = request.POST.get("email", "").strip().lower()
        if not email:
            messages.error(request, "Please enter your email address.")
            return redirect(reverse("indieauth:login") + "#email")

        # Rate limiting: max OTP_RATE_LIMIT sends per email per hour
        rate_key = f"otp_rate:{email}"
        count = cache.get(rate_key, 0)
        if count >= OTP_RATE_LIMIT:
            messages.error(request, "Too many login attempts. Please try again later.")
            return redirect(reverse("indieauth:login") + "#email")

        # Get or create identity + user
        try:
            identity = EmailIdentity.objects.select_related("user").get(email=email)
        except EmailIdentity.DoesNotExist:
            from apps.users.models import User
            user = User.objects.create_user(username=uuid.uuid4().hex[:16])
            identity = EmailIdentity.objects.create(user=user, email=email)

        otp = EmailOTP.generate(identity)

        send_mail(
            subject="Your vtodo login code",
            message=(
                f"Your login code is: {otp.code}\n\n"
                "This code expires in 15 minutes. "
                "If you didn't request this, you can ignore this email."
            ),
            from_email=None,  # uses DEFAULT_FROM_EMAIL from settings
            recipient_list=[email],
            fail_silently=True,
        )

        # Increment rate limit counter
        cache.set(rate_key, count + 1, OTP_RATE_WINDOW)

        request.session["email_identity_pk"] = identity.pk
        return redirect(reverse("emailauth:verify"))


class VerifyOTPView(View):
    """Show OTP entry form (GET) and validate submitted code (POST)."""

    def get(self, request):
        identity_pk = request.session.get("email_identity_pk")
        if not identity_pk:
            return redirect(reverse("indieauth:login") + "#email")
        identity = get_object_or_404(EmailIdentity, pk=identity_pk)
        return render(request, "emailauth/verify.html", {"email": identity.email})

    def post(self, request):
        identity_pk = request.session.get("email_identity_pk")
        if not identity_pk:
            messages.error(request, "Session expired. Please request a new code.")
            return redirect(reverse("indieauth:login") + "#email")

        identity = get_object_or_404(EmailIdentity, pk=identity_pk)
        submitted_code = request.POST.get("code", "").strip()

        otp = (
            EmailOTP.objects.filter(
                identity=identity,
                used_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .order_by("-created_at")
            .first()
        )

        if not otp or otp.code != submitted_code:
            messages.error(request, "Invalid or expired code. Please try again.")
            return render(request, "emailauth/verify.html", {"email": identity.email})

        otp.used_at = timezone.now()
        otp.save(update_fields=["used_at"])

        if not identity.verified:
            identity.verified = True
            identity.save(update_fields=["verified"])

        request.session.pop("email_identity_pk", None)
        login(request, identity.user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect(reverse("boards:board"))
