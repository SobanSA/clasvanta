from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('academics', '0005_appbranding'),
    ]

    operations = [
        migrations.AddField(
            model_name='appbranding',
            name='institute_name',
            field=models.CharField(default='Clasvanta', max_length=140),
        ),
    ]
