from django.db import migrations, models


def migrate_status_to_filter_config(apps, schema_editor):
    Column = apps.get_model("boards", "Column")
    for col in Column.objects.all():
        col.filter_config = {"statuses": [col.status], "tags": [], "due": None}
        col.save(update_fields=["filter_config"])


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="column",
            name="filter_config",
            field=models.JSONField(default=dict),
        ),
        migrations.RunPython(migrate_status_to_filter_config, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(
            name="column",
            unique_together=set(),
        ),
        migrations.RemoveField(
            model_name="column",
            name="status",
        ),
    ]
