from datetime import date
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods
from accounts.views import role_required
from academics.models import AcademicTerm, ClassSubject, StudentProfile, WeeklySchedule
from .models import AttendanceSettings, MakeupClass, LectureSession, AttendanceRecord, AttendanceAudit, SessionDeletionAudit
from .services import (
    can_write, is_admin, submit_attendance, cancel_class,
    create_makeup_class, review_makeup_class, delete_held_session,
)


def _student_count(offering):
    linked_ids = list(offering.class_groups.values_list('pk', flat=True)) or [offering.class_group_id]
    return StudentProfile.objects.filter(
        memberships__class_group_id__in=linked_ids,
        memberships__term=offering.term,
    ).distinct().count(), len(linked_ids) > 1


def _session_for(offering_id, day, number):
    return LectureSession.objects.filter(
        class_subject_id=offering_id, lecture_date=day, lecture_number=number,
    ).select_related('submitted_by').first()


def _schedule_today(user):
    today = timezone.localdate()
    regular = WeeklySchedule.objects.filter(
        weekday=today.weekday(), class_subject__class_groups__term__is_active=True,
    ).select_related(
        'class_subject__class_group__term', 'class_subject__subject', 'class_subject__lecturer'
    ).prefetch_related('class_subject__class_groups').distinct()
    makeups = MakeupClass.objects.filter(
        lecture_date=today, status=MakeupClass.APPROVED,
        class_subject__class_groups__term__is_active=True,
    ).select_related(
        'class_subject__class_group__term', 'class_subject__subject', 'class_subject__lecturer'
    ).prefetch_related('class_subject__class_groups').distinct()
    if not is_admin(user):
        regular = regular.filter(class_subject__lecturer=user)
        makeups = makeups.filter(class_subject__lecturer=user)

    items = []
    for sch in regular:
        offering = sch.class_subject
        count, merged = _student_count(offering)
        items.append({
            'source': 'REGULAR', 'schedule': sch, 'makeup': None,
            'offering': offering, 'lecture_number': sch.lecture_number,
            'session': _session_for(offering.pk, today, sch.lecture_number),
            'student_count': count, 'merged': merged,
            'can_edit': can_write(user, offering, today),
        })
    for makeup in makeups:
        offering = makeup.class_subject
        count, merged = _student_count(offering)
        items.append({
            'source': 'MAKEUP', 'schedule': None, 'makeup': makeup,
            'offering': offering, 'lecture_number': makeup.lecture_number,
            'session': _session_for(offering.pk, today, makeup.lecture_number),
            'student_count': count, 'merged': merged,
            'can_edit': can_write(user, offering, today),
        })
    return sorted(items, key=lambda x: (x['lecture_number'], x['offering'].subject.name.lower()))


@role_required('LECTURER')
def lecturer_dashboard(request):
    policy, _ = AttendanceSettings.objects.get_or_create(pk=1)
    return render(request, 'attendance/lecturer_dashboard.html', {
        'today': timezone.localdate(), 'lectures': _schedule_today(request.user),
        'policy': policy,
    })


def _roster_for(offering):
    return list(StudentProfile.objects.filter(
        memberships__class_group_id__in=(list(offering.class_groups.values_list('pk', flat=True)) or [offering.class_group_id]),
        memberships__term=offering.term,
    ).select_related('user').distinct().order_by('user__username'))


def _mark_context(user, offering, day, number, session=None, makeup=None):
    cancelled = bool(session and session.status == 'CANCELLED')
    if session and session.status == 'SUBMITTED':
        records = list(AttendanceRecord.objects.filter(session=session).select_related('student__user').order_by('student__user__username'))
        roster = [{'student': rec.student, 'present': rec.status == 'P'} for rec in records]
    elif cancelled:
        roster = []
    else:
        roster = [{'student': student, 'present': True} for student in _roster_for(offering)]

    other = AttendanceRecord.objects.filter(
        student_id__in=[row['student'].pk for row in roster],
        session__lecture_date=day, session__status='SUBMITTED',
    ).select_related('session__class_subject__subject').order_by('session__lecture_number')
    if session:
        other = other.exclude(session=session)
    history = {}
    for record in other:
        history.setdefault(record.student_id, []).append({
            'subject': record.session.class_subject.subject.short_name,
            'number': record.session.lecture_number,
            'status': record.get_status_display(), 'absent': record.status == 'A',
        })
    for row in roster:
        row['history'] = history.get(row['student'].pk, [])
        row['warnings'] = sum(1 for item in row['history'] if item['absent'])
    return {
        'offering': offering, 'day': day, 'lecture_number': number,
        'session': session, 'roster': roster, 'makeup': makeup,
        'cancelled': cancelled,
        'editable': can_write(user, offering, day) and not cancelled,
        'admin_mode': is_admin(user), 'super_admin': user.is_superuser,
    }


def _submitted_ids(request):
    raw = request.POST.getlist('present_ids')
    if any(not v.isdigit() for v in raw):
        raise ValidationError('Invalid attendance form submission.')
    return {int(value) for value in raw}


@role_required('LECTURER', 'ADMIN')
@require_http_methods(['GET', 'POST'])
def mark_schedule(request, pk):
    schedule = get_object_or_404(
        WeeklySchedule.objects.select_related('class_subject__class_group__term', 'class_subject__subject').prefetch_related('class_subject__class_groups'), pk=pk,
    )
    offering = schedule.class_subject
    today = timezone.localdate()
    if not is_admin(request.user) and offering.lecturer_id != request.user.pk:
        raise PermissionDenied
    if today.weekday() != schedule.weekday:
        raise PermissionDenied('Scheduled lecture is not today.')
    session = _session_for(offering.pk, today, schedule.lecture_number)
    if request.method == 'POST':
        try:
            sess, num = submit_attendance(
                actor=request.user, offering_id=offering.pk, lecture_date=today,
                lecture_number=schedule.lecture_number, present_ids=_submitted_ids(request),
                reason=request.POST.get('reason', ''),
            )
            messages.success(request, f'Class recorded as held. {num} student record(s) recorded or changed.')
            return redirect('session_detail', pk=sess.pk)
        except (ValidationError, ValueError, PermissionDenied) as exc:
            messages.error(request, f'Could not save attendance: {exc}')
    return render(request, 'attendance/mark.html', _mark_context(request.user, offering, today, schedule.lecture_number, session))


@role_required('LECTURER', 'ADMIN')
@require_http_methods(['GET', 'POST'])
def mark_makeup(request, pk):
    makeup = get_object_or_404(
        MakeupClass.objects.select_related('class_subject__class_group__term', 'class_subject__subject', 'class_subject__lecturer').prefetch_related('class_subject__class_groups'),
        pk=pk, status=MakeupClass.APPROVED,
    )
    offering = makeup.class_subject
    if not is_admin(request.user) and offering.lecturer_id != request.user.pk:
        raise PermissionDenied
    session = _session_for(offering.pk, makeup.lecture_date, makeup.lecture_number)
    if request.method == 'POST':
        try:
            sess, num = submit_attendance(
                actor=request.user, offering_id=offering.pk, lecture_date=makeup.lecture_date,
                lecture_number=makeup.lecture_number, present_ids=_submitted_ids(request),
                reason=request.POST.get('reason', ''),
            )
            messages.success(request, f'Make-up class recorded as held. {num} student record(s) recorded or changed.')
            return redirect('session_detail', pk=sess.pk)
        except (ValidationError, ValueError, PermissionDenied) as exc:
            messages.error(request, f'Could not save attendance: {exc}')
    return render(request, 'attendance/mark.html', _mark_context(
        request.user, offering, makeup.lecture_date, makeup.lecture_number, session, makeup=makeup,
    ))


@role_required('LECTURER', 'ADMIN')
@require_POST
def cancel_occurrence(request):
    try:
        offering_id = int(request.POST.get('offering', ''))
        day = date.fromisoformat(request.POST.get('day', ''))
        number = int(request.POST.get('number', ''))
        session, changed = cancel_class(
            actor=request.user, offering_id=offering_id, lecture_date=day,
            lecture_number=number, reason=request.POST.get('reason', ''),
        )
        messages.success(request, 'Class marked as cancelled.' if changed else 'Class was already cancelled.')
    except (ValueError, ValidationError, PermissionDenied) as exc:
        messages.error(request, f'Could not cancel class: {exc}')
    if is_admin(request.user):
        return redirect(f"{reverse('admin_sessions')}?date={request.POST.get('day','')}")
    return redirect('lecturer_dashboard')


@role_required('LECTURER', 'ADMIN')
@require_http_methods(['GET', 'POST'])
def session_detail(request, pk):
    session = get_object_or_404(LectureSession.objects.select_related('class_subject__class_group__term', 'class_subject__subject').prefetch_related('class_subject__class_groups'), pk=pk)
    offering = session.class_subject
    if not is_admin(request.user) and offering.lecturer_id != request.user.pk and session.submitted_by_id != request.user.pk:
        raise PermissionDenied
    makeup = MakeupClass.objects.filter(
        class_subject=offering, lecture_date=session.lecture_date,
        lecture_number=session.lecture_number, status=MakeupClass.APPROVED,
    ).first()
    if request.method == 'POST':
        if session.status == 'CANCELLED':
            messages.error(request, 'Cancelled classes cannot accept attendance.')
            return redirect('session_detail', pk=session.pk)
        if not is_admin(request.user) and offering.lecturer_id != request.user.pk:
            raise PermissionDenied('This section is no longer assigned to you.')
        try:
            _, num = submit_attendance(
                actor=request.user, offering_id=offering.pk,
                lecture_date=session.lecture_date, lecture_number=session.lecture_number,
                present_ids=_submitted_ids(request), reason=request.POST.get('reason', ''),
            )
            messages.success(request, f'Saved {num} correction(s).')
            return redirect('session_detail', pk=session.pk)
        except (ValidationError, ValueError, PermissionDenied) as exc:
            messages.error(request, f'Could not save: {exc}')
    return render(request, 'attendance/mark.html', _mark_context(
        request.user, offering, session.lecture_date, session.lecture_number, session, makeup=makeup,
    ))


@role_required('ADMIN')
@require_http_methods(['GET', 'POST'])
def delete_session(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied('Only the super admin can delete a held attendance session.')
    session = get_object_or_404(
        LectureSession.objects.select_related(
            'class_subject__subject', 'class_subject__class_group__term', 'class_subject__lecturer', 'submitted_by'
        ).prefetch_related('class_subject__class_groups'),
        pk=pk,
    )
    if session.status != 'SUBMITTED':
        messages.error(request, 'Only a Held session can be deleted.')
        return redirect('session_detail', pk=session.pk)

    records = list(session.records.select_related('student__user').order_by('student__user__username'))
    present_count = sum(record.status == AttendanceRecord.PRESENT for record in records)
    absent_count = sum(record.status == AttendanceRecord.ABSENT for record in records)
    if request.method == 'POST':
        try:
            lecture_date = session.lecture_date
            delete_held_session(
                actor=request.user, session_id=session.pk, reason=request.POST.get('reason', ''),
            )
            messages.success(
                request,
                'Held session deleted. Its scheduled occurrence is Pending/Not Marked again and affected fines were recalculated.',
            )
            return redirect(f"{reverse('admin_sessions')}?date={lecture_date.isoformat()}")
        except (ValidationError, PermissionDenied, LectureSession.DoesNotExist) as exc:
            messages.error(request, f'Could not delete held session: {exc}')

    return render(request, 'attendance/delete_session.html', {
        'session': session, 'offering': session.class_subject,
        'records': records, 'present_count': present_count, 'absent_count': absent_count,
    })


@role_required('LECTURER')
def lecturer_history(request):
    sessions = LectureSession.objects.filter(
        Q(class_subject__lecturer=request.user) | Q(submitted_by=request.user),
    ).distinct().select_related('class_subject__subject', 'submitted_by').prefetch_related(
        'class_subject__class_groups',
    ).order_by('-lecture_date', 'lecture_number')[:200]
    return render(request, 'attendance/lecturer_history.html', {
        'sessions': sessions, 'today': timezone.localdate(),
    })


def _day_rows(selected_date, active):
    regular = WeeklySchedule.objects.none()
    makeups = MakeupClass.objects.none()
    if active and active.start_date <= selected_date <= active.end_date:
        regular = WeeklySchedule.objects.filter(
            weekday=selected_date.weekday(), class_subject__class_groups__term=active,
        ).select_related(
            'class_subject__class_group__term', 'class_subject__subject', 'class_subject__lecturer',
        ).prefetch_related('class_subject__class_groups').distinct()
        makeups = MakeupClass.objects.filter(
            lecture_date=selected_date, status=MakeupClass.APPROVED,
            class_subject__class_groups__term=active,
        ).select_related(
            'class_subject__class_group__term', 'class_subject__subject', 'class_subject__lecturer',
        ).prefetch_related('class_subject__class_groups').distinct()
    rows = []
    for sch in regular:
        count, merged = _student_count(sch.class_subject)
        rows.append({
            'source': 'REGULAR', 'schedule': sch, 'makeup': None,
            'offering': sch.class_subject, 'lecture_number': sch.lecture_number,
            'session': _session_for(sch.class_subject_id, selected_date, sch.lecture_number),
            'student_count': count, 'merged': merged,
        })
    for makeup in makeups:
        count, merged = _student_count(makeup.class_subject)
        rows.append({
            'source': 'MAKEUP', 'schedule': None, 'makeup': makeup,
            'offering': makeup.class_subject, 'lecture_number': makeup.lecture_number,
            'session': _session_for(makeup.class_subject_id, selected_date, makeup.lecture_number),
            'student_count': count, 'merged': merged,
        })
    return sorted(rows, key=lambda x: (x['lecture_number'], x['offering'].subject.name.lower()))


@role_required('ADMIN')
def admin_sessions(request):
    today = timezone.localdate()
    raw_date = request.GET.get('date', '').strip()
    selected_date = today
    if raw_date:
        try:
            selected_date = date.fromisoformat(raw_date)
        except ValueError:
            messages.error(request, 'Invalid attendance date. Showing today instead.')
    active = AcademicTerm.objects.filter(is_active=True).first()
    date_in_term = bool(active and active.start_date <= selected_date <= active.end_date)
    rows = _day_rows(selected_date, active) if date_in_term else []
    held_count = sum(1 for row in rows if row['session'] and row['session'].status == 'SUBMITTED')
    cancelled_count = sum(1 for row in rows if row['session'] and row['session'].status == 'CANCELLED')
    pending_count = sum(1 for row in rows if not row['session'])
    return render(request, 'attendance/admin_sessions.html', {
        'selected_date': selected_date, 'today': today,
        'is_today': selected_date == today, 'is_future': selected_date > today,
        'schedule_rows': rows, 'scheduled_count': len(rows),
        'held_count': held_count, 'cancelled_count': cancelled_count, 'pending_count': pending_count,
        'active_term': active, 'date_in_term': date_in_term,
        'super_admin': request.user.is_superuser,
    })


@role_required('ADMIN', 'LECTURER')
@require_http_methods(['GET', 'POST'])
def makeup_classes(request):
    active = AcademicTerm.objects.filter(is_active=True).first()
    if is_admin(request.user):
        offerings = ClassSubject.objects.filter(class_groups__term=active, lecturer__isnull=False) if active else ClassSubject.objects.none()
    else:
        offerings = ClassSubject.objects.filter(class_groups__term=active, lecturer=request.user) if active else ClassSubject.objects.none()
    offerings = offerings.select_related('subject', 'lecturer', 'class_group__term').prefetch_related('class_groups').distinct().order_by('subject__name')

    if request.method == 'POST':
        action = request.POST.get('action', 'create')
        try:
            if action == 'create':
                offering_id = int(request.POST.get('offering', ''))
                day = date.fromisoformat(request.POST.get('lecture_date', ''))
                number = int(request.POST.get('lecture_number', ''))
                if not offerings.filter(pk=offering_id).exists():
                    raise PermissionDenied('You cannot arrange a make-up class for this subject section.')
                makeup = create_makeup_class(
                    actor=request.user, offering_id=offering_id, lecture_date=day,
                    lecture_number=number, note=request.POST.get('request_note', ''),
                )
                if makeup.status == MakeupClass.APPROVED:
                    messages.success(request, 'Make-up class arranged and approved.')
                else:
                    messages.success(request, 'Make-up class request sent to the super admin for approval.')
            elif action in ('approve', 'reject'):
                makeup = review_makeup_class(
                    actor=request.user, makeup_id=int(request.POST.get('makeup_id', '')),
                    approve=(action == 'approve'), note=request.POST.get('review_note', ''),
                )
                messages.success(request, 'Make-up request approved.' if action == 'approve' else 'Make-up request rejected.')
            else:
                raise ValidationError('Unknown make-up class action.')
            return redirect('makeup_classes')
        except (ValueError, ValidationError, PermissionDenied, ClassSubject.DoesNotExist, MakeupClass.DoesNotExist) as exc:
            messages.error(request, f'Could not update make-up class: {exc}')

    requests = MakeupClass.objects.select_related(
        'class_subject__subject', 'class_subject__lecturer', 'requested_by', 'reviewed_by', 'class_subject__class_group__term'
    ).prefetch_related('class_subject__class_groups')
    if active:
        requests = requests.filter(class_subject__class_group__term=active)
    if not is_admin(request.user):
        requests = requests.filter(requested_by=request.user)
    requests = list(requests.order_by('-lecture_date', 'lecture_number', '-created_at')[:250])
    for item in requests:
        item.session_obj = _session_for(item.class_subject_id, item.lecture_date, item.lecture_number) if item.status == MakeupClass.APPROVED else None
    return render(request, 'attendance/makeup_classes.html', {
        'active_term': active, 'offerings': offerings, 'requests': requests,
        'today': timezone.localdate(), 'admin_mode': is_admin(request.user),
        'super_admin': request.user.is_superuser,
    })


@role_required('ADMIN')
@require_http_methods(['GET', 'POST'])
def admin_new_session(request):
    offering_id = request.GET.get('offering') or request.POST.get('offering')
    day_text = request.GET.get('day') or request.POST.get('day')
    number_text = request.GET.get('number') or request.POST.get('number') or '1'
    context = {
        'offerings': ClassSubject.objects.filter(class_groups__term__is_active=True).select_related('class_group__term', 'subject', 'lecturer').prefetch_related('class_groups').distinct().order_by('subject__code'),
        'offering_id': offering_id, 'day_text': day_text, 'number_text': number_text,
    }
    if offering_id and day_text:
        try:
            day = date.fromisoformat(day_text)
            number = int(number_text)
            offering = ClassSubject.objects.select_related('class_group__term', 'subject').prefetch_related('class_groups').get(pk=int(offering_id))
            existing = LectureSession.objects.filter(class_subject=offering, lecture_date=day, lecture_number=number).first()
            if existing:
                return redirect('session_detail', pk=existing.pk)
            if request.method == 'POST':
                session, num = submit_attendance(
                    actor=request.user, offering_id=offering.pk, lecture_date=day,
                    lecture_number=number, present_ids=_submitted_ids(request),
                )
                messages.success(request, f'Created held class with {num} student record(s).')
                return redirect('session_detail', pk=session.pk)
            return render(request, 'attendance/mark.html', _mark_context(request.user, offering, day, number))
        except (ValueError, ClassSubject.DoesNotExist, ValidationError, PermissionDenied) as exc:
            messages.error(request, f'Invalid lecture selection: {exc}')
    return render(request, 'attendance/new_session.html', context)


@role_required('ADMIN', 'LECTURER')
def audit_log(request):
    logs = AttendanceAudit.objects.select_related(
        'actor', 'student__user', 'session__class_subject__subject', 'session__class_subject__class_group',
    )
    deletions = SessionDeletionAudit.objects.select_related(
        'deleted_by', 'originally_submitted_by', 'class_subject__subject', 'class_subject__class_group',
    ).prefetch_related('class_subject__class_groups')
    if not is_admin(request.user):
        logs = logs.filter(Q(session__class_subject__lecturer=request.user) | Q(session__submitted_by=request.user)).distinct()
        deletions = deletions.filter(
            Q(class_subject__lecturer=request.user) | Q(originally_submitted_by=request.user)
        ).distinct()
    action = request.GET.get('action')
    if action in ['CREATE', 'EDIT']:
        logs = logs.filter(action=action)
        deletions = deletions.none()
    elif action == 'DELETE':
        logs = logs.none()
    return render(request, 'attendance/audit.html', {
        'logs': logs[:200], 'deletions': deletions[:100], 'action_filter': action,
    })

