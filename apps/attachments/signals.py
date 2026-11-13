"""Queue vUpload deletes in the same transaction as the vTodo delete."""

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver

from apps.attachments.models import Attachment, PendingDeletion
from apps.workspaces.models import Workspace


def _process_after_commit():
    from apps.attachments.services import process_pending_deletions

    def run():
        try:
            process_pending_deletions()
        except Exception:  # the beat task retries; never fail the request
            import logging

            logging.getLogger(__name__).exception("vUpload deletes failed; will retry")

    transaction.on_commit(run)


@receiver(post_delete, sender=Attachment)
def queue_file_deletion(sender, instance, origin=None, **kwargs):
    # A workspace going away (directly, or with its owner's account) deletes
    # every file in one owner call, queued below. No need for one per file.
    if isinstance(origin, Workspace) or isinstance(origin, _user_model()):
        return
    PendingDeletion.objects.create(kind=PendingDeletion.KIND_FILE, target=str(instance.file_id))
    _process_after_commit()


@receiver(pre_delete, sender=Workspace)
def queue_owner_deletion(sender, instance, **kwargs):
    from apps.attachments.services import owner_for

    PendingDeletion.objects.create(kind=PendingDeletion.KIND_OWNER, target=owner_for(instance.pk))
    _process_after_commit()


def _user_model():
    from django.apps import apps

    return apps.get_model(settings.AUTH_USER_MODEL)
