"""Give every task a stable iCalendar UID for .ics export and import.

The column is added nullable, filled with a fresh UUID per row (a field
default would hand every existing row the same value), then made required.
"""

import uuid

from django.db import migrations, models

import apps.tasks.models


def fill_uids(apps, schema_editor):
    Task = apps.get_model("tasks", "Task")
    for task in Task.objects.filter(ical_uid__isnull=True).only("pk").iterator():
        Task.objects.filter(pk=task.pk).update(ical_uid=str(uuid.uuid4()))


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0015_task_completion_follows_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="ical_uid",
            field=models.CharField(max_length=255, null=True),
        ),
        migrations.RunPython(fill_uids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="task",
            name="ical_uid",
            field=models.CharField(default=apps.tasks.models.new_ical_uid, max_length=255),
        ),
        migrations.AddConstraint(
            model_name="task",
            constraint=models.UniqueConstraint(
                fields=("workspace", "ical_uid"), name="task_unique_workspace_ical_uid"
            ),
        ),
    ]
