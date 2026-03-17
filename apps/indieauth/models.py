from django.conf import settings
from django.db import models


class IndieAuthIdentity(models.Model):
    """
    Links a User to their IndieWeb identity (their personal website URL).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="indieauth_identities",
    )
    me = models.URLField(max_length=2000, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.me
