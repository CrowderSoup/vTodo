from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_default_task_statuses(sender, instance, created, **kwargs):
    if not created:
        return

    from apps.tasks.services import provision_statuses

    provision_statuses(user=instance)
