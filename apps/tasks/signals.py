from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_default_task_statuses(sender, instance, created, **kwargs):
    if not created:
        return

    from apps.tasks.models import TaskStatus

    defaults = [
        ("Backlog", "backlog", 0, False),
        ("To Do", "todo", 1, False),
        ("In Progress", "in_progress", 2, False),
        ("Done", "done", 3, True),
    ]
    for name, slug, order, is_done in defaults:
        TaskStatus.objects.create(
            user=instance,
            name=name,
            slug=slug,
            order=order,
            is_done=is_done,
        )
