"""Append-only financial ledger. Call these functions inside transaction.atomic()."""
from decimal import Decimal
from django.db.models import Sum
from .models import FineLedgerEntry, FinePolicy
from attendance.models import AttendanceRecord


def reconcile_fine(student, offering, actor=None):
    """Recalculate charges for one student/subject/semester without editing ledger history.

    The caller holds a DB lock on the StudentProfile, preventing parallel charge
    reconciliation from duplicating fine entries.
    """
    term = offering.term
    policy, _ = FinePolicy.objects.get_or_create(term=term)
    absence_count = AttendanceRecord.objects.filter(
        student=student, status=AttendanceRecord.ABSENT,
        session__status='SUBMITTED', session__class_subject=offering,
    ).count()
    target = Decimal(max(0, absence_count - policy.allowed_absences)) * policy.rate_per_extra_absence
    current = FineLedgerEntry.objects.filter(
        student=student, class_subject=offering,
        kind__in=['CHARGE', 'ADJUSTMENT'],
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    difference = target - current
    if difference:
        FineLedgerEntry.objects.create(
            student=student, class_subject=offering,
            kind='CHARGE' if difference > 0 else 'ADJUSTMENT',
            amount=difference,
            note=f'Automatic recalculation: {absence_count} absence(s), {policy.allowed_absences} allowed',
            actor=actor,
        )


def subject_balance(student, offering):
    return FineLedgerEntry.objects.filter(
        student=student, class_subject=offering,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
