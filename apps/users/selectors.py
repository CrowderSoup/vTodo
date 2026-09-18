import hashlib

from django.conf import settings


def is_admin(user) -> bool:
    if not user.is_authenticated:
        return False
    return user.email_identities.filter(verified=True, email__in=settings.ADMIN_EMAILS).exists()


def gravatar_url(user) -> str:
    """Gravatar fallback for users with no Google avatar. Uses the oldest
    verified email as the account's "primary" one, since we don't track
    a separate primary flag. `d=404` makes Gravatar 404 instead of serving
    a placeholder when the email has no registered image, so the template
    can fall back to the letter avatar via an <img onerror> handler."""
    if not user.is_authenticated:
        return ""
    identity = user.email_identities.filter(verified=True).order_by("created_at").first()
    if not identity:
        return ""
    digest = hashlib.sha256(identity.email.strip().lower().encode()).hexdigest()
    return f"https://www.gravatar.com/avatar/{digest}?s=160&d=404"
