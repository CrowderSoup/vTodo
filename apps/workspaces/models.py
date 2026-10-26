from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Workspace(models.Model):
    """A personal workspace belongs to one user. A shared workspace is a team.

    Personal and shared stay apart: a personal workspace has no members but
    its owner, and a shared workspace has no single owner column. Sharing
    happens by membership on a shared workspace, not by adding someone to a
    personal one.
    """

    KIND_PERSONAL = "personal"
    KIND_SHARED = "shared"
    KIND_CHOICES = [
        (KIND_PERSONAL, "Personal"),
        (KIND_SHARED, "Shared"),
    ]

    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    # Set for a personal workspace, empty for a shared one.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="personal_workspace_owned",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner"],
                condition=models.Q(kind="personal"),
                name="one_personal_workspace_per_user",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(kind="personal", owner__isnull=False)
                    | models.Q(kind="shared", owner__isnull=True)
                ),
                name="workspace_kind_matches_owner",
            ),
        ]

    def __str__(self):
        return self.name


class Membership(models.Model):
    ROLE_OWNER = "owner"
    ROLE_MEMBER = "member"
    ROLE_VIEWER = "viewer"
    ROLE_CHOICES = [
        (ROLE_OWNER, "Owner"),
        (ROLE_MEMBER, "Member"),
        (ROLE_VIEWER, "Viewer"),
    ]

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"],
                name="one_membership_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.user} @ {self.workspace} ({self.role})"

    def save(self, *args, **kwargs):
        workspace = self.workspace
        if workspace.kind == Workspace.KIND_PERSONAL and (
            self.user_id != workspace.owner_id or self.role != self.ROLE_OWNER
        ):
            raise ValidationError("A personal workspace only has its owner.")
        super().save(*args, **kwargs)
