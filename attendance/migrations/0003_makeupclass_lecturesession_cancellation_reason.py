from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0004_classsubject_class_groups'),
        ('attendance', '0002_attendanceaudit_actor_role'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='lecturesession',
            name='cancellation_reason',
            field=models.CharField(blank=True, default='', max_length=400),
        ),
        migrations.AlterField(
            model_name='lecturesession',
            name='status',
            field=models.CharField(choices=[('SUBMITTED', 'Held'), ('CANCELLED', 'Cancelled')], default='SUBMITTED', max_length=12),
        ),
        migrations.CreateModel(
            name='MakeupClass',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('lecture_date', models.DateField(db_index=True)),
                ('lecture_number', models.PositiveSmallIntegerField()),
                ('request_note', models.CharField(blank=True, max_length=400)),
                ('status', models.CharField(choices=[('PENDING', 'Pending approval'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected')], db_index=True, default='PENDING', max_length=12)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('review_note', models.CharField(blank=True, max_length=400)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('class_subject', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='makeup_classes', to='academics.classsubject')),
                ('requested_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='makeup_requests', to=settings.AUTH_USER_MODEL)),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='reviewed_makeup_requests', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-lecture_date', 'lecture_number', '-created_at'],
            },
        ),
    ]
