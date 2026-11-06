from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ('academics', '0001_initial'),
        ('accounts', '0002_user_must_change_password'),
    ]
    operations = [
        migrations.CreateModel(name='AttendanceSettings', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('working_start', models.TimeField(default='08:00')),
            ('working_end', models.TimeField(default='16:00')),
        ]),
        migrations.CreateModel(name='LectureSession', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('lecture_date', models.DateField()),
            ('lecture_number', models.PositiveSmallIntegerField()),
            ('status', models.CharField(max_length=12, choices=[('SUBMITTED', 'Submitted'), ('CANCELLED', 'Cancelled')], default='SUBMITTED')),
            ('submitted_at', models.DateTimeField(auto_now_add=True)),
            ('class_subject', models.ForeignKey(to='academics.classsubject', on_delete=django.db.models.deletion.PROTECT, related_name='lecture_sessions')),
            ('submitted_by', models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT, related_name='submitted_sessions')),
        ], options={'ordering': ['-lecture_date', 'lecture_number']}),
        migrations.CreateModel(name='AttendanceRecord', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('status', models.CharField(max_length=1, choices=[('P', 'Present'), ('A', 'Absent')])),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('session', models.ForeignKey(to='attendance.lecturesession', on_delete=django.db.models.deletion.PROTECT, related_name='records')),
            ('student', models.ForeignKey(to='academics.studentprofile', on_delete=django.db.models.deletion.PROTECT, related_name='attendance_records')),
        ]),
        migrations.CreateModel(name='AttendanceAudit', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('action', models.CharField(max_length=8, choices=[('CREATE', 'Initial submission'), ('EDIT', 'Correction')])),
            ('old_status', models.CharField(max_length=1, blank=True)),
            ('new_status', models.CharField(max_length=1, choices=[('P', 'Present'), ('A', 'Absent')])),
            ('reason', models.CharField(max_length=400, blank=True)),
            ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
            ('session', models.ForeignKey(to='attendance.lecturesession', on_delete=django.db.models.deletion.PROTECT, related_name='audit_logs')),
            ('record', models.ForeignKey(to='attendance.attendancerecord', on_delete=django.db.models.deletion.PROTECT, related_name='audit_logs')),
            ('student', models.ForeignKey(to='academics.studentprofile', on_delete=django.db.models.deletion.PROTECT)),
            ('actor', models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT)),
        ], options={'ordering': ['-created_at', '-id']}),
        migrations.AddConstraint(model_name='lecturesession', constraint=models.UniqueConstraint(fields=('class_subject', 'lecture_date', 'lecture_number'), name='unique_lecture_occurrence')),
        migrations.AddConstraint(model_name='attendancerecord', constraint=models.UniqueConstraint(fields=('session', 'student'), name='one_mark_per_student_lecture')),
    ]
