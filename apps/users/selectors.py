from django.conf import settings


def is_admin(user) -> bool:
    if not user.is_authenticated:
        return False
    return user.email_identities.filter(verified=True, email__in=settings.ADMIN_EMAILS).exists()


def primary_email(user) -> str:
    """The account's "primary" email, shown in Settings so users can confirm
    which Google account they're signed in as. Uses the oldest verified
    identity, since we don't track a separate primary flag."""
    if not user.is_authenticated:
        return ""
    identity = user.email_identities.filter(verified=True).order_by("created_at").first()
    return identity.email if identity else ""
