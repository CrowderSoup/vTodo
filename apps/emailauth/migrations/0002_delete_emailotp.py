from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('emailauth', '0001_initial'),
    ]

    operations = [
        migrations.DeleteModel(
            name='EmailOTP',
        ),
    ]
