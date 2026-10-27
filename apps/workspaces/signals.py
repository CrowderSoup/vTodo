from django.conf import settings
from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver

from apps.workspaces.services import (
    ensure_personal_workspace,
    hand_off_shared_workspaces,
    personal_workspace_id,
)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_personal_workspace(sender, instance, created, raw=False, **kwargs):
    if raw or not created:
        return
    ensure_personal_workspace(instance)


@receiver(pre_delete, sender=settings.AUTH_USER_MODEL)
def keep_shared_workspaces_owned(sender, instance, **kwargs):
    hand_off_shared_workspaces(instance)


def _assign_workspace(sender, instance, raw=False, **kwargs):
    if raw or instance.workspace_id is not None or not instance.user_id:
        return
    instance.workspace_id = personal_workspace_id(instance.user_id)


def connect_workspace_assignment():
    """Imported from ready() so the task and board apps don't import us back."""
    from apps.boards.models import Board
    from apps.tasks.models import Task, TaskActivity, TaskStatus

    for model in (Task, TaskStatus, TaskActivity, Board):
        pre_save.connect(
            _assign_workspace,
            sender=model,
            weak=False,
            dispatch_uid=f"assign-workspace-{model._meta.label_lower}",
        )
