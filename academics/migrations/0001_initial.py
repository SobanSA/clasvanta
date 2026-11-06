from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [('accounts', '0002_user_must_change_password')]
    operations = [
        migrations.CreateModel(name='Programme', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('code', models.CharField(max_length=24, unique=True)),
            ('name', models.CharField(max_length=180)),
        ], options={'ordering': ['code']}),
        migrations.CreateModel(name='AcademicTerm', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('name', models.CharField(max_length=90, unique=True, help_text='Example: Fall 2026')),
            ('start_date', models.DateField()), ('end_date', models.DateField()),
            ('is_active', models.BooleanField(default=False)),
        ], options={'ordering': ['-start_date']}),
        migrations.CreateModel(name='Subject', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('code', models.CharField(max_length=40, unique=True)),
            ('name', models.CharField(max_length=180)),
            ('short_name', models.CharField(max_length=40)),
        ], options={'ordering': ['code']}),
        migrations.CreateModel(name='StudentProfile', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('user', models.OneToOneField(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT, related_name='student_profile')),
        ]),
        migrations.CreateModel(name='ClassGroup', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('code', models.CharField(max_length=48, help_text='Example: BSCS-1A')),
            ('semester_number', models.PositiveSmallIntegerField(default=1)),
            ('programme', models.ForeignKey(to='academics.programme', on_delete=django.db.models.deletion.PROTECT, related_name='classes')),
            ('term', models.ForeignKey(to='academics.academicterm', on_delete=django.db.models.deletion.PROTECT, related_name='classes')),
        ], options={'ordering': ['code']}),
        migrations.CreateModel(name='ClassSubject', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('class_group', models.ForeignKey(to='academics.classgroup', on_delete=django.db.models.deletion.PROTECT, related_name='class_subjects')),
            ('subject', models.ForeignKey(to='academics.subject', on_delete=django.db.models.deletion.PROTECT, related_name='class_subjects')),
            ('lecturer', models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT, related_name='teaching_assignments', null=True, blank=True)),
        ], options={'ordering': ['class_group__code', 'subject__short_name']}),
        migrations.CreateModel(name='ClassMembership', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('student', models.ForeignKey(to='academics.studentprofile', on_delete=django.db.models.deletion.PROTECT, related_name='memberships')),
            ('term', models.ForeignKey(to='academics.academicterm', on_delete=django.db.models.deletion.PROTECT, related_name='memberships')),
            ('class_group', models.ForeignKey(to='academics.classgroup', on_delete=django.db.models.deletion.PROTECT, related_name='memberships')),
        ]),
        migrations.CreateModel(name='WeeklySchedule', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('weekday', models.PositiveSmallIntegerField(choices=[(0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'), (3, 'Thursday'), (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday')])),
            ('lecture_number', models.PositiveSmallIntegerField(default=1)),
            ('class_subject', models.ForeignKey(to='academics.classsubject', on_delete=django.db.models.deletion.PROTECT, related_name='weekly_schedules')),
        ], options={'ordering': ['weekday', 'lecture_number', 'class_subject__class_group__code']}),
        migrations.AddConstraint(model_name='classgroup', constraint=models.UniqueConstraint(fields=('term', 'code'), name='unique_class_code_per_term')),
        migrations.AddConstraint(model_name='classsubject', constraint=models.UniqueConstraint(fields=('class_group', 'subject'), name='unique_subject_per_class')),
        migrations.AddConstraint(model_name='classmembership', constraint=models.UniqueConstraint(fields=('student', 'term'), name='unique_student_term_membership')),
        migrations.AddConstraint(model_name='weeklyschedule', constraint=models.UniqueConstraint(fields=('class_subject', 'weekday', 'lecture_number'), name='unique_subject_day_lecture')),
    ]
