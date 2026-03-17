from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0003_add_task_is_archived'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='recurrence_days',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='task',
            name='recurrence_from',
            field=models.CharField(
                choices=[('completion', 'Completion date'), ('due_date', 'Due date')],
                default='completion',
                max_length=10,
            ),
        ),
    ]
