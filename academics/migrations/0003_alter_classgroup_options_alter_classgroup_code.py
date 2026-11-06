from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('academics', '0002_class_names_subject_sections'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='classgroup',
            options={'ordering': ['programme__code', 'semester_number', 'code']},
        ),
        migrations.AlterField(
            model_name='classgroup',
            name='code',
            field=models.CharField(help_text='Example: BSCS-S1', max_length=48),
        ),
    ]
