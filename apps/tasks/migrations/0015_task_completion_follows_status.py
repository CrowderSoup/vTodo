"""Make completed_at agree with the status column (see apps/tasks/lifecycle.py).

Before the lifecycle was explicit, a task could be created straight into a
done status, or sit in a status later flipped to/from is_done, and keep the
wrong completed_at. Tasks in a done status without completed_at are marked
completed as of their last update; tasks outside one lose completed_at.
"""

from django.db import migrations
from django.db.models import Exists, F, OuterRef


def forwards(apps, schema_editor):
    Task = apps.get_model("tasks", "Task")
    TaskStatus = apps.get_model("tasks", "TaskStatus")

    in_done_status = Exists(
        TaskStatus.objects.filter(
            workspace_id=OuterRef("workspace_id"), slug=OuterRef("status"), is_done=True
        )
    )
    Task.objects.filter(in_done_status, completed_at__isnull=True).update(
        completed_at=F("updated_at"), claimed_by=None, claim_expires_at=None
    )
    Task.objects.filter(~in_done_status, completed_at__isnull=False).update(
        completed_at=None, previous_status=""
    )


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0014_task_assignee_and_claims"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
