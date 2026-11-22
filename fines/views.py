from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from accounts.views import role_required
from academics.branding import get_app_branding
from academics.models import ClassMembership, ClassSubject, StudentProfile
from attendance.models import AttendanceRecord

from .models import FineLedgerEntry, FinePolicy


def _student_outstanding_rows(student):
    rows = list(
        FineLedgerEntry.objects.filter(student=student)
        .values('class_subject_id')
        .annotate(balance=Sum('amount'))
        .order_by('class_subject__subject__name')
    )
    positive = [row for row in rows if row['balance'] and row['balance'] > 0]
    offerings = {
        item.pk: item
        for item in ClassSubject.objects.filter(
            pk__in=[row['class_subject_id'] for row in positive]
        ).select_related('subject', 'class_group__term').prefetch_related('class_groups')
    }
    return [(row, offerings.get(row['class_subject_id'])) for row in positive if offerings.get(row['class_subject_id'])]


@role_required('ADMIN')
@require_http_methods(['GET', 'POST'])
def fines_dashboard(request):
    if request.method == 'POST':
        try:
            with transaction.atomic():
                student = StudentProfile.objects.select_for_update().get(pk=int(request.POST['student']))
                offering = ClassSubject.objects.get(pk=int(request.POST['offering']))
                amount = Decimal(request.POST['amount'])
                if amount <= 0:
                    raise ValueError('Payment must be greater than 0.')
                if not student.memberships.filter(class_group_id__in=offering.linked_class_ids()).exists():
                    raise ValueError('Student is not in one of the classes linked to this subject section.')
                current = FineLedgerEntry.objects.filter(
                    student=student, class_subject=offering,
                ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
                if amount > current:
                    raise ValueError('Payment exceeds outstanding balance.')
                FineLedgerEntry.objects.create(
                    student=student,
                    class_subject=offering,
                    amount=-amount,
                    kind='PAYMENT',
                    note=request.POST.get('reference', '')[:300],
                    actor=request.user,
                )
            messages.success(request, 'Payment recorded.')
            return redirect('fines_dashboard')
        except (ValueError, InvalidOperation, StudentProfile.DoesNotExist, ClassSubject.DoesNotExist) as exc:
            messages.error(request, f'Unable to record payment: {exc}')

    rows = list(
        FineLedgerEntry.objects.values(
            'student_id', 'student__user__username', 'student__user__first_name',
            'student__user__last_name', 'class_subject_id',
            'class_subject__subject__short_name',
        ).annotate(balance=Sum('amount')).order_by('student__user__username')
    )
    offering_map = {
        item.pk: item
        for item in ClassSubject.objects.filter(
            pk__in=[row['class_subject_id'] for row in rows]
        ).prefetch_related('class_groups')
    }
    balances = []
    for row in rows:
        if row['balance'] > 0:
            offering = offering_map.get(row['class_subject_id'])
            row['class_codes'] = offering.class_codes_display if offering else ''
            row['student_name'] = (
                ' '.join(filter(None, [row['student__user__first_name'], row['student__user__last_name']])).strip()
                or row['student__user__username']
            )
            balances.append(row)
    return render(request, 'fines/dashboard.html', {'balances': balances})


@role_required('ADMIN')
@require_GET
def fine_challan(request, student_id):
    """Printable A5 payment challan for one student's current outstanding fines."""
    student = get_object_or_404(
        StudentProfile.objects.select_related('user'),
        pk=student_id,
    )
    outstanding = _student_outstanding_rows(student)
    if not outstanding:
        messages.info(request, 'This student has no outstanding fine to print.')
        return redirect('fines_dashboard')

    course_rows = []
    total_absences = 0
    total_fineable = 0
    total_payable = Decimal('0.00')
    offering_ids = []

    for row, offering in outstanding:
        policy = FinePolicy.objects.filter(term=offering.term).first() or FinePolicy(term=offering.term)
        absences = AttendanceRecord.objects.filter(
            student=student,
            status=AttendanceRecord.ABSENT,
            session__status='SUBMITTED',
            session__class_subject=offering,
        ).count()
        fineable = max(0, absences - policy.allowed_absences)
        balance = row['balance'] or Decimal('0.00')
        total_absences += absences
        total_fineable += fineable
        total_payable += balance
        offering_ids.append(offering.pk)
        course_rows.append({
            'offering': offering,
            'absences': absences,
            'allowed': policy.allowed_absences,
            'fineable': fineable,
            'rate': policy.rate_per_extra_absence,
            'balance': balance,
        })

    membership = (
        ClassMembership.objects.filter(student=student, term__is_active=True)
        .select_related('class_group__programme', 'term')
        .order_by('-term__start_date')
        .first()
        or ClassMembership.objects.filter(student=student)
        .select_related('class_group__programme', 'term')
        .order_by('-term__start_date')
        .first()
    )

    issue_date = timezone.localdate()
    due_date = issue_date + timedelta(days=7)
    has_payments = FineLedgerEntry.objects.filter(
        student=student,
        class_subject_id__in=offering_ids,
        kind='PAYMENT',
    ).exists()
    branding = get_app_branding()

    context = {
        'student': student,
        'membership': membership,
        'course_rows': course_rows,
        'total_absences': total_absences,
        'total_fineable': total_fineable,
        'total_payable': total_payable,
        'issue_date': issue_date,
        'due_date': due_date,
        'challan_number': f'CF-{issue_date.year}-{student.pk:05d}',
        'payment_status': 'PARTIALLY PAID' if has_payments else 'NOT PAID',
        'institute_name': branding.institute_name or 'Clasvanta',
        'app_name': branding.app_name or 'Clasvanta',
    }
    return render(request, 'fines/challan.html', context)
