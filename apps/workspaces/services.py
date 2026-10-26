"""Creating the one personal workspace every user has.

Shared workspaces are a later step. This module only makes sure the personal
one exists and that tasks, statuses, boards, and history rows point at it.
"""

from apps.workspaces.models import Membership, Workspace

PERSONAL_WORKSPACE_NAME = "Personal"


def ensure_personal_workspace(user):
    """The user's personal workspace, creating it and the owner membership."""
    workspace, _created = Workspace.objects.get_or_create(
        owner=user,
        kind=Workspace.KIND_PERSONAL,
        defaults={"name": PERSONAL_WORKSPACE_NAME},
    )
    Membership.objects.get_or_create(
        workspace=workspace,
        user=user,
        defaults={"role": Membership.ROLE_OWNER},
    )
    return workspace


def personal_workspace_id(user_id):
    workspace_id = (
        Workspace.objects.filter(owner_id=user_id, kind=Workspace.KIND_PERSONAL)
        .values_list("pk", flat=True)
        .first()
    )
    if workspace_id is not None:
        return workspace_id
    from django.contrib.auth import get_user_model

    return ensure_personal_workspace(get_user_model().objects.get(pk=user_id)).pk


def backfill_personal_workspaces(user_model, workspace_model, membership_model):
    """Give every user a personal workspace. Used by the data migration and tests.

    The model classes are passed in so the migration can hand over its
    historical models.
    """
    for user in user_model.objects.all().iterator():
        workspace, _created = workspace_model.objects.get_or_create(
            owner_id=user.pk,
            kind="personal",
            defaults={"name": PERSONAL_WORKSPACE_NAME},
        )
        membership_model.objects.get_or_create(
            workspace_id=workspace.pk,
            user_id=user.pk,
            defaults={"role": "owner"},
        )


def backfill_workspace_rows(row_model, workspace_model):
    """Point rows that have a user and no workspace at that user's personal one."""
    workspaces = {
        owner_id: pk
        for owner_id, pk in workspace_model.objects.filter(kind="personal").values_list(
            "owner_id", "pk"
        )
    }
    missing = []
    for owner_id in (
        row_model.objects.filter(workspace__isnull=True)
        .values_list("user_id", flat=True)
        .distinct()
    ):
        workspace_id = workspaces.get(owner_id)
        if workspace_id is None:
            missing.append(owner_id)
            continue
        row_model.objects.filter(user_id=owner_id, workspace__isnull=True).update(
            workspace_id=workspace_id
        )
    if missing:
        raise RuntimeError(
            "No personal workspace for user id(s): " + ", ".join(str(pk) for pk in missing)
        )
