from django.db import migrations, models


def populate_labels(apps, schema_editor):
    ClassGroup = apps.get_model('academics', 'ClassGroup')
    ClassSubject = apps.get_model('academics', 'ClassSubject')
    for group in ClassGroup.objects.all():
        if not group.name:
            group.name = f'Semester {group.semester_number}'
            group.save(update_fields=['name'])
    for offering in ClassSubject.objects.select_related('subject').all():
        if not offering.section_code:
            offering.section_code = offering.subject.short_name
            offering.save(update_fields=['section_code'])


class Migration(migrations.Migration):
    dependencies = [('academics', '0001_initial')]
    operations = [
        migrations.AddField(
            model_name='classgroup',
            name='name',
            field=models.CharField(blank=True, default='', help_text='Example: Semester 1', max_length=120),
        ),
        migrations.AddField(
            model_name='classsubject',
            name='section_code',
            field=models.CharField(blank=True, default='', help_text='Subject-based section label. If blank, the subject short name is used.', max_length=60),
        ),
        migrations.RunPython(populate_labels, migrations.RunPython.noop),
    ]
