"""Student-facing portal views for Clasvanta v2.7.

All data is derived from the authenticated student's own StudentProfile. No
student selector or student id is accepted by these views.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from accounts.models import User
from attendance.models import AttendanceRecord, LectureSession, MakeupClass
from fines.models import FineLedgerEntry, FinePolicy
from fines.services import subject_balance

from .models import ClassMembership, ClassSubject, StudentProfile, WeeklySchedule


def student_required(view_func):
    """Allow only real student accounts and preserve forced-password-change flow."""
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if request.user.must_change_password:
            return redirect('password_change')
        if request.user.is_superuser or request.user.role != User.Role.STUDENT:
            raise PermissionDenied('This page is available to student accounts only.')
        return view_func(request, *args, **kwargs)
    return wrapped


def _student_scope(user):
    profile = get_object_or_404(StudentProfile.objects.select_related('user'), user=user)
    membership = ClassMembership.objects.filter(
        student=profile,
        term__is_active=True,
    ).select_related(
        'term', 'class_group__programme', 'class_group__term',
    ).order_by('-term__start_date', '-pk').first()
    return profile, membership


def _assigned_offerings(membership):
    """Return subject sections for the student's class, including legacy fallback rows."""
    if not membership:
        return []
    group = membership.class_group
    return list(ClassSubject.objects.filter(
        Q(class_groups=group) |
        Q(class_group=group, class_groups__isnull=True),
    ).select_related(
        'subject', 'lecturer', 'class_group__term',
    ).prefetch_related('class_groups').distinct().order_by('subject__name', 'subject__code'))


def _makeup_keys(offerings):
    offering_ids = [offering.pk for offering in offerings]
    if not offering_ids:
        return set()
    return set(MakeupClass.objects.filter(
        class_subject_id__in=offering_ids,
        status=MakeupClass.APPROVED,
    ).values_list('class_subject_id', 'lecture_date', 'lecture_number'))


def _attendance_rows(profile, membership, offerings):
    """Build per-subject Held-only attendance summaries and histories."""
    if not membership:
        return [], {
            'total': 0, 'present': 0, 'absent': 0, 'percentage': None,
            'fine_total': Decimal('0.00'), 'warning_count': 0,
        }, None

    policy, _ = FinePolicy.objects.get_or_create(term=membership.term)
    offering_ids = [offering.pk for offering in offerings]
    records_by_offering = defaultdict(list)
    if offering_ids:
        records = AttendanceRecord.objects.filter(
            student=profile,
            session__class_subject_id__in=offering_ids,
            session__status='SUBMITTED',
        ).select_related(
            'session__class_subject__subject', 'session__submitted_by',
        ).order_by('-session__lecture_date', '-session__lecture_number', '-pk')
        for record in records:
            records_by_offering[record.session.class_subject_id].append(record)

    makeup_keys = _makeup_keys(offerings)
    rows = []
    summary = {
        'total': 0, 'present': 0, 'absent': 0, 'percentage': None,
        'fine_total': Decimal('0.00'), 'warning_count': 0,
    }

    for offering in offerings:
        records = records_by_offering.get(offering.pk, [])
        total = len(records)
        present = sum(1 for record in records if record.status == AttendanceRecord.PRESENT)
        absent = total - present
        percentage = round((present * 100) / total, 1) if total else None
        remaining = max(0, policy.allowed_absences - absent)
        excess = max(0, absent - policy.allowed_absences)
        balance = subject_balance(profile, offering)
        fine_due = max(Decimal('0.00'), balance)
        credit = max(Decimal('0.00'), -balance)

        if excess:
            warning_level = 'danger'
            warning_text = f'{excess} absence(s) beyond the allowed limit'
        elif total and remaining == 0:
            warning_level = 'warning'
            warning_text = 'No allowed absences remaining'
        elif total and remaining == 1:
            warning_level = 'warning'
            warning_text = 'Only 1 allowed absence remaining'
        else:
            warning_level = 'ok'
            warning_text = 'Within the allowed absence limit'

        history = []
        for record in records:
            session = record.session
            history.append({
                'record': record,
                'date': session.lecture_date,
                'lecture_number': session.lecture_number,
                'status': record.status,
                'status_label': record.get_status_display(),
                'source': 'Make-up' if (
                    offering.pk, session.lecture_date, session.lecture_number
                ) in makeup_keys else 'Regular',
            })

        summary['total'] += total
        summary['present'] += present
        summary['absent'] += absent
        summary['fine_total'] += fine_due
        if warning_level in {'warning', 'danger'}:
            summary['warning_count'] += 1

        rows.append({
            'offering': offering,
            'total': total,
            'present': present,
            'absent': absent,
            'percentage': percentage,
            'allowed_remaining': remaining,
            'excess_absences': excess,
            'fine_balance': fine_due,
            'credit': credit,
            'warning_level': warning_level,
            'warning_text': warning_text,
            'history': history,
        })

    if summary['total']:
        summary['percentage'] = round((summary['present'] * 100) / summary['total'], 1)
    return rows, summary, policy


def _schedule_rows(profile, membership, offerings, selected_date):
    """Return regular and approved make-up classes for one date for this student."""
    if (
        not membership or
        selected_date < membership.term.start_date or
        selected_date > membership.term.end_date
    ):
        return []

    offering_ids = [offering.pk for offering in offerings]
    if not offering_ids:
        return []
    offering_map = {offering.pk: offering for offering in offerings}

    regular = WeeklySchedule.objects.filter(
        class_subject_id__in=offering_ids,
        weekday=selected_date.weekday(),
    ).select_related('class_subject__subject').order_by('lecture_number', 'class_subject__subject__name')

    makeups = MakeupClass.objects.filter(
        class_subject_id__in=offering_ids,
        lecture_date=selected_date,
        status=MakeupClass.APPROVED,
    ).select_related('class_subject__subject').order_by('lecture_number', 'class_subject__subject__name')

    sessions = {
        (session.class_subject_id, session.lecture_number): session
        for session in LectureSession.objects.filter(
            class_subject_id__in=offering_ids,
            lecture_date=selected_date,
        ).select_related('submitted_by')
    }
    marks = {
        (record.session.class_subject_id, record.session.lecture_number): record.status
        for record in AttendanceRecord.objects.filter(
            student=profile,
            session__class_subject_id__in=offering_ids,
            session__lecture_date=selected_date,
            session__status='SUBMITTED',
        ).select_related('session')
    }

    today = timezone.localdate()
    rows = []

    def append_row(offering_id, lecture_number, source, makeup=None):
        key = (offering_id, lecture_number)
        session = sessions.get(key)
        mark = marks.get(key)
        if session and session.status == 'CANCELLED':
            state = 'CANCELLED'
            state_label = 'Cancelled'
        elif session and session.status == 'SUBMITTED':
            state = 'HELD'
            state_label = 'Held'
        elif selected_date < today:
            state = 'PENDING'
            state_label = 'Not marked'
        else:
            state = 'SCHEDULED'
            state_label = 'Scheduled'
        rows.append({
            'offering': offering_map[offering_id],
            'lecture_number': lecture_number,
            'source': source,
            'makeup': makeup,
            'session': session,
            'state': state,
            'state_label': state_label,
            'mark': mark,
            'mark_label': dict(AttendanceRecord.STATUS).get(mark, '') if mark else '',
        })

    for schedule in regular:
        append_row(schedule.class_subject_id, schedule.lecture_number, 'REGULAR')
    for makeup in makeups:
        append_row(makeup.class_subject_id, makeup.lecture_number, 'MAKEUP', makeup=makeup)

    rows.sort(key=lambda row: (
        row['lecture_number'], row['offering'].subject.name.lower(), row['source'],
    ))
    return rows


@student_required
@require_GET
def dashboard(request):
    profile, membership = _student_scope(request.user)
    today = timezone.localdate()
    offerings = _assigned_offerings(membership)
    subjects, summary, policy = _attendance_rows(profile, membership, offerings)
    today_rows = _schedule_rows(profile, membership, offerings, today)
    makeup_today = sum(1 for row in today_rows if row['source'] == 'MAKEUP')

    return render(request, 'student/dashboard.html', {
        'profile': profile,
        'membership': membership,
        'today': today,
        'subjects': subjects,
        'attendance_summary': summary,
        'overall_percentage': summary['percentage'],
        'fine_total': summary['fine_total'],
        'allowed_absences': policy.allowed_absences if policy else 0,
        'today_schedule': today_rows,  # backward-compatible context key
        'today_rows': today_rows,
        'makeup_today': makeup_today,
        'warning_subjects': [row for row in subjects if row['warning_level'] in {'warning', 'danger'}],
    })


@student_required
@require_GET
def my_attendance(request):
    profile, membership = _student_scope(request.user)
    offerings = _assigned_offerings(membership)
    subjects, summary, policy = _attendance_rows(profile, membership, offerings)
    return render(request, 'student/attendance.html', {
        'profile': profile,
        'membership': membership,
        'subjects': subjects,
        'summary': summary,
        'allowed_absences': policy.allowed_absences if policy else 0,
    })


@student_required
@require_GET
def my_schedule(request):
    profile, membership = _student_scope(request.user)
    today = timezone.localdate()
    selected_date = today
    invalid_date = False
    raw_date = request.GET.get('date', '').strip()
    if raw_date:
        try:
            selected_date = date.fromisoformat(raw_date)
        except ValueError:
            invalid_date = True
            selected_date = today

    offerings = _assigned_offerings(membership)
    rows = _schedule_rows(profile, membership, offerings, selected_date)
    return render(request, 'student/schedule.html', {
        'profile': profile,
        'membership': membership,
        'today': today,
        'selected_date': selected_date,
        'invalid_date': invalid_date,
        'rows': rows,
    })


@student_required
@require_GET
def my_fines(request):
    profile, membership = _student_scope(request.user)
    offerings = _assigned_offerings(membership)
    subjects, summary, policy = _attendance_rows(profile, membership, offerings)
    fine_rows = []

    if membership and policy:
        offering_ids = [offering.pk for offering in offerings]
        ledger_by_offering = defaultdict(list)
        if offering_ids:
            for entry in FineLedgerEntry.objects.filter(
                student=profile,
                class_subject_id__in=offering_ids,
            ).select_related('actor').order_by('-created_at', '-pk'):
                ledger_by_offering[entry.class_subject_id].append(entry)

        for row in subjects:
            offering = row['offering']
            absence_history = [item for item in reversed(row['history']) if item['status'] == AttendanceRecord.ABSENT]
            for index, item in enumerate(absence_history, start=1):
                item['chargeable'] = index > policy.allowed_absences
                item['absence_number'] = index

            entries = ledger_by_offering.get(offering.pk, [])
            charge_total = sum((entry.amount for entry in entries if entry.kind == 'CHARGE'), Decimal('0.00'))
            adjustment_total = sum((entry.amount for entry in entries if entry.kind == 'ADJUSTMENT'), Decimal('0.00'))
            payment_total = sum((entry.amount for entry in entries if entry.kind == 'PAYMENT'), Decimal('0.00'))
            gross_target = Decimal(row['excess_absences']) * policy.rate_per_extra_absence
            fine_rows.append({
                **row,
                'absence_history': absence_history,
                'entries': entries,
                'charge_total': charge_total,
                'adjustment_total': adjustment_total,
                'payment_total': abs(payment_total),
                'gross_target': gross_target,
                'rate': policy.rate_per_extra_absence,
            })

    return render(request, 'student/fines.html', {
        'profile': profile,
        'membership': membership,
        'rows': fine_rows,
        'fine_total': summary['fine_total'],
        'policy': policy,
    })


@student_required
@require_GET
def profile(request):
    profile_obj, membership = _student_scope(request.user)
    assigned_subject_count = len(_assigned_offerings(membership)) if membership else 0
    return render(request, 'student/profile.html', {
        'profile': profile_obj,
        'membership': membership,
        'assigned_subject_count': assigned_subject_count,
    })
