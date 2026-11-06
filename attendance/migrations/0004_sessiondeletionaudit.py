from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0004_classsubject_class_groups'),
        ('attendance', '0003_makeupclass_lecturesession_cancellation_reason'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SessionDeletionAudit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('original_session_id', models.PositiveBigIntegerField(db_index=True)),
                ('lecture_date', models.DateField(db_index=True)),
                ('lecture_number', models.PositiveSmallIntegerField()),
                ('originally_submitted_at', models.DateTimeField()),
                ('reason', models.CharField(max_length=400)),
                ('record_count', models.PositiveIntegerField(default=0)),
                ('present_count', models.PositiveIntegerField(default=0)),
                ('absent_count', models.PositiveIntegerField(default=0)),
                ('snapshot', models.JSONField(default=dict)),
                ('deleted_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('class_subject', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='session_deletion_audits', to='academics.classsubject')),
                ('deleted_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='deleted_attendance_sessions', to=settings.AUTH_USER_MODEL)),
                ('originally_submitted_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='originally_submitted_deleted_sessions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-deleted_at', '-id'],
            },
        ),
    ]
