from django.db import migrations, models


def create_accounts_group_and_sync(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    User = apps.get_model('accounts', 'User')
    group, _ = Group.objects.get_or_create(name='Accounts')
    User.objects.filter(groups=group).update(role='ACCOUNTS', is_staff=False)


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0002_user_must_change_password'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('ADMIN', 'Administrator'),
                    ('ACCOUNTS', 'Accounts'),
                    ('LECTURER', 'Lecturer'),
                    ('STUDENT', 'Student'),
                ],
                default='STUDENT',
                max_length=10,
            ),
        ),
        migrations.RunPython(
            create_accounts_group_and_sync,
            migrations.RunPython.noop,
        ),
    ]
