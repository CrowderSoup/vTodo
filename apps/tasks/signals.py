from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_default_task_statuses(sender, instance, created, **kwargs):
    if not created:
        return

    from apps.tasks.models import DEFAULT_STATUS_DEFS, TaskStatus

    for name, slug, order, is_done in DEFAULT_STATUS_DEFS:
        TaskStatus.objects.create(
            user=instance,
            name=name,
            slug=slug,
            order=order,
            is_done=is_done,
        )
