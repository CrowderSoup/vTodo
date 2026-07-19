from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0005_backfill_team_boards"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="board",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("team__isnull", True), ("user__isnull", False)),
                    models.Q(("team__isnull", False), ("user__isnull", True)),
                    _connector="OR",
                ),
                name="board_exactly_one_owner",
            ),
        ),
        migrations.AddConstraint(
            model_name="board",
            constraint=models.UniqueConstraint(
                condition=models.Q(("team__isnull", True)),
                fields=("user",),
                name="board_unique_user",
            ),
        ),
        migrations.AddConstraint(
            model_name="board",
            constraint=models.UniqueConstraint(
                condition=models.Q(("user__isnull", True)),
                fields=("team",),
                name="board_unique_team",
            ),
        ),
    ]
