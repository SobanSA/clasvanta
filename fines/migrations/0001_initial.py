from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from decimal import Decimal


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ('academics', '0001_initial'),
        ('accounts', '0002_user_must_change_password'),
    ]
    operations = [
        migrations.CreateModel(name='FinePolicy', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('allowed_absences', models.PositiveSmallIntegerField(default=2)),
            ('rate_per_extra_absence', models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('500.00'))),
            ('term', models.OneToOneField(to='academics.academicterm', on_delete=django.db.models.deletion.PROTECT, related_name='fine_policy')),
        ]),
        migrations.CreateModel(name='FineLedgerEntry', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('kind', models.CharField(max_length=12, choices=[('CHARGE', 'Fine charge'), ('ADJUSTMENT', 'Fine adjustment'), ('PAYMENT', 'Payment')])),
            ('amount', models.DecimalField(max_digits=12, decimal_places=2)),
            ('note', models.CharField(max_length=300, blank=True)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('student', models.ForeignKey(to='academics.studentprofile', on_delete=django.db.models.deletion.PROTECT, related_name='fine_entries')),
            ('class_subject', models.ForeignKey(to='academics.classsubject', on_delete=django.db.models.deletion.PROTECT, related_name='fine_entries')),
            ('actor', models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT, null=True, blank=True)),
        ], options={'ordering': ['-created_at', '-id']}),
    ]
