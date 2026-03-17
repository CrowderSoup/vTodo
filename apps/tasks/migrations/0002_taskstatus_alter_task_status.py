import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskStatus",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("slug", models.SlugField(max_length=50)),
                ("order", models.PositiveSmallIntegerField(default=0)),
                ("color", models.CharField(blank=True, default="", max_length=7)),
                ("is_done", models.BooleanField(default=False)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="task_statuses", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["order"],
                "unique_together": {("user", "slug")},
            },
        ),
        migrations.AlterField(
            model_name="task",
            name="status",
            field=models.CharField(default="todo", max_length=50),
        ),
    ]
