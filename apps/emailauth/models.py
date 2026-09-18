from django.conf import settings
from django.db import models


class EmailIdentity(models.Model):
    """Links a User to their verified sign-in email address (currently always
    populated via Google OAuth). Used to match a Google login to an existing
    account, for admin-email checks, and for team-invite acceptance."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_identities",
    )
    email = models.EmailField(unique=True)
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email
