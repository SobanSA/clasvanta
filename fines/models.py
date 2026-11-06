from decimal import Decimal
from django.conf import settings
from django.db import models


class FinePolicy(models.Model):
    term = models.OneToOneField('academics.AcademicTerm', on_delete=models.PROTECT, related_name='fine_policy')
    allowed_absences = models.PositiveSmallIntegerField(default=2)
    rate_per_extra_absence = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('500.00'))

    def __str__(self):
        return f'{self.term} — {self.allowed_absences} free / Rs {self.rate_per_extra_absence}'


class FineLedgerEntry(models.Model):
    KINDS = [('CHARGE', 'Fine charge'), ('ADJUSTMENT', 'Fine adjustment'), ('PAYMENT', 'Payment')]
    student = models.ForeignKey('academics.StudentProfile', on_delete=models.PROTECT, related_name='fine_entries')
    class_subject = models.ForeignKey('academics.ClassSubject', on_delete=models.PROTECT, related_name='fine_entries')
    kind = models.CharField(max_length=12, choices=KINDS)
    # Positive: charge, negative: reversal or payment.
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.CharField(max_length=300, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
