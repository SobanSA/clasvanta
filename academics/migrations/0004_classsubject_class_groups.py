from django.db import migrations, models


def seed_existing_class_links(apps, schema_editor):
    ClassSubject = apps.get_model('academics', 'ClassSubject')
    for offering in ClassSubject.objects.all().iterator():
        if offering.class_group_id:
            offering.class_groups.add(offering.class_group_id)


def reverse_seed(apps, schema_editor):
    ClassSubject = apps.get_model('academics', 'ClassSubject')
    for offering in ClassSubject.objects.all().iterator():
        offering.class_groups.clear()


class Migration(migrations.Migration):
    dependencies = [
        ('academics', '0003_alter_classgroup_options_alter_classgroup_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='classsubject',
            name='class_groups',
            field=models.ManyToManyField(blank=True, related_name='subject_sections', to='academics.classgroup'),
        ),
        migrations.RunPython(seed_existing_class_links, reverse_seed),
    ]
