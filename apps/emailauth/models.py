from django.conf import settings
from django.db import models


class EmailIdentity(models.Model):
    """Links a User to a verified sign-in email (Google or Pocket ID).

    A new social login matches an existing account through this row, and
    admin-email checks use it too. Emails are stored lower-cased.
    """

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
