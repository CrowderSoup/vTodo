import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.tasks import activity
from apps.tasks.models import Task, TaskActivity
from apps.users.models import User
from apps.workspaces.models import Membership, Workspace
from apps.workspaces.services import backfill_personal_workspaces, ensure_personal_workspace


@pytest.mark.django_db
def test_new_user_gets_one_personal_workspace():
    user = User.objects.create_user()

    workspace = Workspace.objects.get(owner=user)
    assert workspace.kind == Workspace.KIND_PERSONAL
    assert workspace.name == "Personal"
    assert Membership.objects.get(workspace=workspace, user=user).role == Membership.ROLE_OWNER
    assert user.board.workspace_id == workspace.pk
    assert set(user.task_statuses.values_list("workspace_id", flat=True)) == {workspace.pk}
    assert ensure_personal_workspace(user).pk == workspace.pk
    assert Workspace.objects.filter(owner=user).count() == 1


@pytest.mark.django_db
def test_new_task_and_its_history_use_the_personal_workspace():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="T")
    activity.record_created(task, actor=user, source=TaskActivity.SOURCE_WEB)

    assert task.workspace_id == user.board.workspace_id
    row = TaskActivity.objects.get(task_pk=task.pk)
    assert row.workspace_id == task.workspace_id


@pytest.mark.django_db
def test_personal_workspace_rejects_another_member_and_a_second_copy():
    user = User.objects.create_user()
    other = User.objects.create_user()
    workspace = Workspace.objects.get(owner=user)

    with pytest.raises(ValidationError):
        Membership.objects.create(
            workspace=workspace, user=other, role=Membership.ROLE_MEMBER
        )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Workspace.objects.create(
                name="Other", kind=Workspace.KIND_PERSONAL, owner=user
            )


@pytest.mark.django_db
def test_shared_workspace_has_members_and_no_owner_column():
    owner = User.objects.create_user()
    viewer = User.objects.create_user()
    workspace = Workspace.objects.create(name="Home", kind=Workspace.KIND_SHARED)
    Membership.objects.create(
        workspace=workspace, user=owner, role=Membership.ROLE_OWNER
    )
    Membership.objects.create(
        workspace=workspace, user=viewer, role=Membership.ROLE_VIEWER
    )

    assert workspace.owner_id is None
    assert set(workspace.memberships.values_list("role", flat=True)) == {"owner", "viewer"}
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Workspace.objects.create(
                name="Nope", kind=Workspace.KIND_SHARED, owner=owner
            )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Workspace.objects.create(name="Nope", kind=Workspace.KIND_PERSONAL)


@pytest.mark.django_db
def test_backfill_covers_a_user_created_without_signals():
    user = User.objects.bulk_create(
        [
            User(
                username="legacy",
                password="!",
                is_active=True,
                is_staff=False,
                is_superuser=False,
                date_joined=timezone.now(),
            )
        ]
    )[0]
    assert not Workspace.objects.filter(owner=user).exists()

    backfill_personal_workspaces(User, Workspace, Membership)

    workspace = Workspace.objects.get(owner=user, kind=Workspace.KIND_PERSONAL)
    assert Membership.objects.get(workspace=workspace, user=user).role == Membership.ROLE_OWNER
