from django.conf import settings
from django.db import migrations, models


def delete_team_owned_statuses(apps, schema_editor):
    """TaskStatus rows with no user (i.e. team-owned) can't survive `user` becoming
    required. There's no real team data on this deployment, so these are just
    dropped rather than reassigned."""
    TaskStatus = apps.get_model("tasks", "TaskStatus")
    TaskStatus.objects.filter(user__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0008_task_due_time_task_duration_minutes'),
    ]

    operations = [
        migrations.RunPython(delete_team_owned_statuses, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name='taskstatus',
            name='taskstatus_exactly_one_owner',
        ),
        migrations.RemoveConstraint(
            model_name='taskstatus',
            name='taskstatus_unique_user_slug',
        ),
        migrations.RemoveConstraint(
            model_name='taskstatus',
            name='taskstatus_unique_team_slug',
        ),
        migrations.RemoveField(
            model_name='taskstatus',
            name='team',
        ),
        migrations.AlterField(
            model_name='taskstatus',
            name='user',
            field=models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='task_statuses', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddConstraint(
            model_name='taskstatus',
            constraint=models.UniqueConstraint(fields=('user', 'slug'), name='taskstatus_unique_user_slug'),
        ),
        migrations.RemoveField(
            model_name='task',
            name='team',
        ),
        migrations.RemoveField(
            model_name='task',
            name='assignee',
        ),
        migrations.DeleteModel(
            name='TaskActivity',
        ),
    ]
