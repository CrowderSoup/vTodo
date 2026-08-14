from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_default_board(sender, instance, created, **kwargs):
    if not created:
        return

    # Local import to avoid circular imports at module load time
    from apps.boards.models import Board

    Board.objects.create(user=instance)
