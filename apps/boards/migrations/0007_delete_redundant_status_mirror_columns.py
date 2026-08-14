from django.db import migrations


def delete_redundant_status_mirror_columns(apps, schema_editor):
    """Statuses now imply their own board lane (see apps.tasks.services.provision_statuses
    and the merged lane rendering in apps.boards.views), so a Column that does nothing
    but mirror a single status -- no tags, no due filter, no assignee filter -- is fully
    redundant and would otherwise show up as a duplicate lane. Anything with real extra
    filtering (multiple statuses, tags, assignee, due) survives as a custom lane.
    """
    Column = apps.get_model("boards", "Column")

    for column in Column.objects.all():
        config = column.filter_config or {}
        statuses = config.get("statuses") or []
        tags = config.get("tags") or []
        due = config.get("due")
        assignee = config.get("assignee", "any")
        if len(statuses) == 1 and not tags and not due and assignee in ("any", "", None):
            column.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0006_board_owner_constraint"),
    ]

    operations = [
        migrations.RunPython(delete_redundant_status_mirror_columns, migrations.RunPython.noop),
    ]
