from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('fines', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='fineledgerentry',
            name='kind',
            field=models.CharField(
                choices=[
                    ('CHARGE', 'Fine charge'),
                    ('ADJUSTMENT', 'Fine adjustment'),
                    ('PAYMENT', 'Payment'),
                    ('CONCESSION', 'Concession'),
                    ('WAIVER', 'Waiver'),
                    ('RELIEF_REVERSAL', 'Relief reversal'),
                ],
                max_length=18,
            ),
        ),
    ]
