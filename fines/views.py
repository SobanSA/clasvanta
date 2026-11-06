from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from accounts.views import role_required
from academics.models import StudentProfile, ClassSubject
from .models import FineLedgerEntry


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
                if not student.memberships.filter(class_group__in=offering.class_groups.all()).exists():
                    raise ValueError('Student is not in one of the classes linked to this subject section.')
                current = FineLedgerEntry.objects.filter(student=student, class_subject=offering).aggregate(total=Sum('amount'))['total'] or Decimal('0')
                if amount > current:
                    raise ValueError('Payment exceeds outstanding balance.')
                FineLedgerEntry.objects.create(
                    student=student, class_subject=offering, amount=-amount, kind='PAYMENT',
                    note=request.POST.get('reference', '')[:300], actor=request.user,
                )
            messages.success(request, 'Payment recorded.')
            return redirect('fines_dashboard')
        except (ValueError, InvalidOperation, StudentProfile.DoesNotExist, ClassSubject.DoesNotExist) as exc:
            messages.error(request, f'Unable to record payment: {exc}')
    rows = list(FineLedgerEntry.objects.values(
        'student_id', 'student__user__username', 'student__user__first_name',
        'class_subject_id', 'class_subject__subject__short_name',
    ).annotate(balance=Sum('amount')).order_by('student__user__username'))
    offering_map = {
        o.pk: o for o in ClassSubject.objects.filter(pk__in=[r['class_subject_id'] for r in rows]).prefetch_related('class_groups')
    }
    balances = []
    for row in rows:
        if row['balance'] > 0:
            offering = offering_map.get(row['class_subject_id'])
            row['class_codes'] = offering.class_codes_display if offering else ''
            balances.append(row)
    return render(request, 'fines/dashboard.html', {'balances': balances})
