from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0001_initial'),
        ('boards', '0008_remove_teams'),
        ('tasks', '0009_remove_teams_and_assignee'),
    ]

    operations = [
        migrations.DeleteModel(
            name='TeamInvite',
        ),
        migrations.DeleteModel(
            name='TeamMembership',
        ),
        migrations.DeleteModel(
            name='Team',
        ),
    ]
