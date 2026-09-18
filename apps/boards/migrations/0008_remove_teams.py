from django.conf import settings
from django.db import migrations, models


def delete_team_boards(apps, schema_editor):
    """Board rows with no user (i.e. team boards) can't survive `user` becoming
    required and unique. There's no real team data on this deployment, so these
    are just dropped -- their Columns and SavedFilters cascade with them."""
    Board = apps.get_model("boards", "Board")
    Board.objects.filter(user__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0007_delete_redundant_status_mirror_columns'),
    ]

    operations = [
        migrations.RunPython(delete_team_boards, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name='board',
            name='board_exactly_one_owner',
        ),
        migrations.RemoveConstraint(
            model_name='board',
            name='board_unique_user',
        ),
        migrations.RemoveConstraint(
            model_name='board',
            name='board_unique_team',
        ),
        migrations.RemoveField(
            model_name='board',
            name='team',
        ),
        migrations.AlterField(
            model_name='board',
            name='user',
            field=models.OneToOneField(on_delete=models.deletion.CASCADE, related_name='boards', to=settings.AUTH_USER_MODEL),
        ),
    ]
