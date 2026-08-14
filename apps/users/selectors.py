from django.conf import settings


def is_admin(user) -> bool:
    if not user.is_authenticated:
        return False
    return user.email_identities.filter(verified=True, email__in=settings.ADMIN_EMAILS).exists()
