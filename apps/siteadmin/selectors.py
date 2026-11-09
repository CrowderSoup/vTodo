from django.db import transaction

from .models import SiteInvite, SiteSettings


def signup_allowed(email: str) -> bool:
    """Whether a brand-new account may be created for this email right now,
    given the current signup_mode. Does not consume an invite -- see
    consume_signup_slot for the version callers creating an account should use."""
    mode = SiteSettings.load().signup_mode
    if mode == SiteSettings.MODE_OPEN:
        return True
    if mode == SiteSettings.MODE_PRIVATE:
        return False
    return SiteInvite.objects.pending().filter(email__iexact=email).exists()


def consume_signup_slot(email: str) -> bool:
    """Check signup_allowed and, for invite_only, atomically mark the matching
    invite accepted in the same transaction -- so two concurrent signup attempts
    for the same invited email can't both succeed."""
    mode = SiteSettings.load().signup_mode
    if mode == SiteSettings.MODE_OPEN:
        return True
    if mode == SiteSettings.MODE_PRIVATE:
        return False

    with transaction.atomic():
        invite = SiteInvite.objects.select_for_update().pending().filter(email__iexact=email).first()
        if not invite:
            return False
        invite.accept()
        return True
