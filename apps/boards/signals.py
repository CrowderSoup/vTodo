from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_default_board(sender, instance, created, **kwargs):
    if not created:
        return

    # Local imports to avoid circular imports at module load time
    from apps.boards.models import Board, Column

    board = Board.objects.create(user=instance)
    default_columns = [
        ("Backlog",     {"statuses": ["backlog"],     "tags": [], "due": None}, 0),
        ("To Do",       {"statuses": ["todo"],         "tags": [], "due": None}, 1),
        ("In Progress", {"statuses": ["in_progress"],  "tags": [], "due": None}, 2),
        ("Done",        {"statuses": ["done"],          "tags": [], "due": None}, 3),
    ]
    for label, filter_config, order in default_columns:
        Column.objects.create(board=board, label=label, filter_config=filter_config, order=order)
