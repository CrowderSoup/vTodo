import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0005_taskcomment"),
        ("users", "0002_user_default_column"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="default_column",
        ),
        migrations.AddField(
            model_name="user",
            name="default_status",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="default_for_users",
                to="tasks.taskstatus",
            ),
        ),
    ]
