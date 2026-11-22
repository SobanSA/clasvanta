from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('academics', '0006_appbranding_institute_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='studentprofile',
            name='father_name',
            field=models.CharField(blank=True, default='', max_length=160),
        ),
    ]
