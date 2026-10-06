from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('siteadmin', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='siteinvite',
            name='token',
        ),
    ]
