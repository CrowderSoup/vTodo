"""Personal workspaces for every user, and shared workspaces people join."""

from django.core.exceptions import ValidationError

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


class MemberError(Exception):
    """A shared-workspace membership change that should be shown to the user."""


def create_shared_workspace(*, user, name):
    """A shared workspace, with the creator as owner and its own board and statuses."""
    name = (name or "").strip()
    if not name:
        raise ValidationError("Give the workspace a name.")
    if len(name) > 255:
        raise ValidationError("That name is too long.")

    workspace = Workspace.objects.create(
        name=name, kind=Workspace.KIND_SHARED, owner=None
    )
    Membership.objects.create(
        workspace=workspace, user=user, role=Membership.ROLE_OWNER
    )
    from apps.boards.models import Board

    Board.objects.create(user=user, workspace=workspace, name=name)
    from apps.tasks.services import provision_statuses

    provision_statuses(user=user, workspace=workspace)
    return workspace


def add_workspace_member(*, workspace, email, role):
    """Add the person who signs in with this email, or change their role."""
    if workspace.kind != Workspace.KIND_SHARED:
        raise MemberError("People can only be added to a shared workspace.")
    if role not in (Membership.ROLE_OWNER, Membership.ROLE_MEMBER, Membership.ROLE_VIEWER):
        raise MemberError("Pick a role.")

    from apps.emailauth.models import EmailIdentity

    identity = (
        EmailIdentity.objects.filter(email__iexact=(email or "").strip(), verified=True)
        .select_related("user")
        .first()
    )
    if identity is None:
        raise MemberError("No one with that email has signed in yet.")

    membership, created = Membership.objects.get_or_create(
        workspace=workspace,
        user=identity.user,
        defaults={"role": role},
    )
    if not created and membership.role != role:
        set_member_role(membership=membership, role=role)
    return membership


def set_member_role(*, membership, role):
    if role not in (Membership.ROLE_OWNER, Membership.ROLE_MEMBER, Membership.ROLE_VIEWER):
        raise MemberError("Pick a role.")
    if membership.role == Membership.ROLE_OWNER and role != Membership.ROLE_OWNER:
        other_owners = membership.workspace.memberships.filter(
            role=Membership.ROLE_OWNER
        ).exclude(pk=membership.pk)
        if not other_owners.exists():
            raise MemberError("A workspace needs an owner.")
    membership.role = role
    membership.save(update_fields=["role"])
    return membership


def remove_workspace_member(*, membership):
    if membership.role == Membership.ROLE_OWNER:
        other_owners = membership.workspace.memberships.filter(
            role=Membership.ROLE_OWNER
        ).exclude(pk=membership.pk)
        if not other_owners.exists():
            raise MemberError("A workspace needs an owner.")
    membership.delete()


def hand_off_shared_workspaces(user):
    """Before `user` is deleted, keep their shared workspaces owned.

    A workspace they own alone passes to the longest-standing member, or to a
    viewer when no member is left. A workspace with nobody else in it goes away.
    """
    owned = Workspace.objects.filter(
        kind=Workspace.KIND_SHARED,
        memberships__user=user,
        memberships__role=Membership.ROLE_OWNER,
    )
    for workspace in owned:
        others = workspace.memberships.exclude(user=user)
        if others.filter(role=Membership.ROLE_OWNER).exists():
            continue
        heir = (
            others.filter(role=Membership.ROLE_MEMBER).order_by("joined_at", "pk").first()
            or others.order_by("joined_at", "pk").first()
        )
        if heir is None:
            workspace.delete()
            continue
        heir.role = Membership.ROLE_OWNER
        heir.save(update_fields=["role"])
