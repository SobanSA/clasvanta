from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('academics', '0007_studentprofile_father_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='studentprofile',
            name='whatsapp_number',
            field=models.CharField(blank=True, default='', max_length=16),
        ),
    ]
