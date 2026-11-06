from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_default_branding(apps, schema_editor):
    AppBranding = apps.get_model('academics', 'AppBranding')
    AppBranding.objects.get_or_create(
        pk=1,
        defaults={
            'app_name': 'Clasvanta',
            'subtitle': 'Academic Attendance & Management',
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ('academics', '0004_classsubject_class_groups'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AppBranding',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('app_name', models.CharField(default='Clasvanta', max_length=80)),
                ('subtitle', models.CharField(default='Academic Attendance & Management', max_length=120)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='branding_updates', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'application branding',
                'verbose_name_plural': 'application branding',
            },
        ),
        migrations.RunPython(seed_default_branding, migrations.RunPython.noop),
    ]
