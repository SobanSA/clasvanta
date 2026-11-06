# Additive field: preserves all existing attendance and audit records.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('attendance', '0001_initial')]
    operations = [
        migrations.AddField(
            model_name='attendanceaudit',
            name='actor_role',
            field=models.CharField(blank=True, default='', help_text='Role captured when the action occurred', max_length=12),
        ),
    ]
