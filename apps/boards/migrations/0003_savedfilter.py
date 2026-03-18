from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0002_column_filter_config"),
    ]

    operations = [
        migrations.CreateModel(
            name="SavedFilter",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("filter_config", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "board",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="saved_filters",
                        to="boards.board",
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
                "unique_together": {("board", "name")},
            },
        ),
    ]
