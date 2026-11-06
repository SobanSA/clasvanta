"""Validated attendance, cancellation and make-up-class workflows."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from academics.models import ClassSubject, StudentProfile, WeeklySchedule
from fines.services import reconcile_fine
from .models import AttendanceSettings, MakeupClass, LectureSession, AttendanceRecord, AttendanceAudit, SessionDeletionAudit


def is_admin(user):
    return user.is_authenticated and user.is_active and (user.is_superuser or user.role == 'ADMIN')


def lecturer_can_write(user, offering, day):
    if not user.is_authenticated or not user.is_active or user.role != 'LECTURER' or user.is_superuser:
        return False
    current = timezone.localtime()
    policy, _ = AttendanceSettings.objects.get_or_create(pk=1)
    return all([
        offering.lecturer_id == user.pk,
        offering.class_group.term.is_active,
        day == timezone.localdate(),
        policy.working_start <= current.time().replace(tzinfo=None) < policy.working_end,
    ])


def can_write(user, offering, day):
    if day > timezone.localdate():
        return False
    return is_admin(user) or lecturer_can_write(user, offering, day)


def approved_makeup(offering, lecture_date, lecture_number):
    return MakeupClass.objects.filter(
        class_subject=offering,
        lecture_date=lecture_date,
        lecture_number=lecture_number,
        status=MakeupClass.APPROVED,
    ).first()


def lecturer_occurrence_allowed(offering, lecture_date, lecture_number):
    regular = WeeklySchedule.objects.filter(
        class_subject=offering,
        weekday=lecture_date.weekday(),
        lecture_number=lecture_number,
    ).exists()
    return regular or bool(approved_makeup(offering, lecture_date, lecture_number))


def validate_makeup_slot(offering, lecture_date, lecture_number, *, exclude_makeup_id=None):
    """Reject one-off slots that clash with a regular or other active make-up lecture."""
    if not offering.pk:
        raise ValidationError('Choose a subject section first.')
    if lecture_number < 1 or lecture_number > 20:
        raise ValidationError('Lecture number must be between 1 and 20.')
    term = offering.term
    if not term or not (term.start_date <= lecture_date <= term.end_date):
        raise ValidationError('Make-up class date is outside the academic term.')
    if lecture_date < timezone.localdate():
        raise ValidationError('A make-up class cannot be arranged for a past date.')
    if not offering.lecturer_id:
        raise ValidationError('Assign a lecturer to this subject section first.')

    linked_ids = offering.linked_class_ids()
    regular = WeeklySchedule.objects.filter(
        weekday=lecture_date.weekday(),
        lecture_number=lecture_number,
        class_subject__class_group__term=term,
    ).select_related('class_subject__subject', 'class_subject__lecturer')
    regular_class_clash = regular.filter(
        Q(class_subject__class_groups__in=linked_ids) |
        Q(class_subject__class_group_id__in=linked_ids, class_subject__class_groups__isnull=True)
    ).distinct().first()
    if regular_class_clash:
        raise ValidationError(
            f'{regular_class_clash.class_subject.class_codes_display} already has '
            f'{regular_class_clash.class_subject.subject.name} in Lecture {lecture_number} on that weekday.'
        )
    teacher_regular = regular.filter(class_subject__lecturer_id=offering.lecturer_id).first()
    if teacher_regular:
        raise ValidationError(
            f'{offering.lecturer.get_full_name() or offering.lecturer.username} already teaches '
            f'{teacher_regular.class_subject.subject.name} in Lecture {lecture_number} on that weekday.'
        )

    makeups = MakeupClass.objects.filter(
        lecture_date=lecture_date,
        lecture_number=lecture_number,
        status__in=[MakeupClass.PENDING, MakeupClass.APPROVED],
    ).select_related('class_subject__subject', 'class_subject__lecturer').prefetch_related('class_subject__class_groups')
    if exclude_makeup_id:
        makeups = makeups.exclude(pk=exclude_makeup_id)
    makeup_class_clash = makeups.filter(
        Q(class_subject__class_groups__in=linked_ids) |
        Q(class_subject__class_group_id__in=linked_ids, class_subject__class_groups__isnull=True)
    ).distinct().first()
    if makeup_class_clash:
        raise ValidationError(
            f'This class already has a {makeup_class_clash.get_status_display().lower()} make-up '
            f'lecture in Lecture {lecture_number} on {lecture_date}.'
        )
    teacher_makeup = makeups.filter(class_subject__lecturer_id=offering.lecturer_id).first()
    if teacher_makeup:
        raise ValidationError(
            f'This lecturer already has a {teacher_makeup.get_status_display().lower()} make-up '
            f'lecture in Lecture {lecture_number} on {lecture_date}.'
        )


@transaction.atomic
def create_makeup_class(*, actor, offering_id, lecture_date, lecture_number, note=''):
    offering = ClassSubject.objects.select_for_update().select_related(
        'class_group__term', 'lecturer', 'subject'
    ).prefetch_related('class_groups').get(pk=offering_id)
    if not is_admin(actor):
        if actor.role != 'LECTURER' or offering.lecturer_id != actor.pk:
            raise PermissionDenied('Lecturers can request make-up classes only for their own assigned subjects.')
    validate_makeup_slot(offering, lecture_date, lecture_number)
    approved_now = is_admin(actor)
    makeup = MakeupClass(
        class_subject=offering,
        lecture_date=lecture_date,
        lecture_number=lecture_number,
        requested_by=actor,
        request_note=note.strip(),
        status=MakeupClass.APPROVED if approved_now else MakeupClass.PENDING,
        reviewed_by=actor if approved_now else None,
        reviewed_at=timezone.now() if approved_now else None,
        review_note='Arranged by administrator.' if approved_now else '',
    )
    makeup.full_clean()
    makeup.save()
    return makeup


@transaction.atomic
def review_makeup_class(*, actor, makeup_id, approve, note=''):
    if not actor.is_superuser:
        raise PermissionDenied('Only the super admin can approve or reject lecturer make-up requests.')
    makeup = MakeupClass.objects.select_for_update().select_related(
        'class_subject__class_group__term', 'class_subject__lecturer', 'class_subject__subject', 'requested_by'
    ).prefetch_related('class_subject__class_groups').get(pk=makeup_id)
    if makeup.status != MakeupClass.PENDING:
        raise ValidationError('This make-up request has already been reviewed.')
    if approve:
        validate_makeup_slot(
            makeup.class_subject, makeup.lecture_date, makeup.lecture_number,
            exclude_makeup_id=makeup.pk,
        )
        makeup.status = MakeupClass.APPROVED
    else:
        makeup.status = MakeupClass.REJECTED
    makeup.reviewed_by = actor
    makeup.reviewed_at = timezone.now()
    makeup.review_note = note.strip()
    makeup.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_note', 'updated_at'])
    return makeup


@transaction.atomic
def cancel_class(*, actor, offering_id, lecture_date, lecture_number, reason=''):
    offering = ClassSubject.objects.select_for_update().select_related('class_group__term').get(pk=offering_id)
    if not can_write(actor, offering, lecture_date):
        raise PermissionDenied('Outside allowed date, hours or lecturer assignment.')
    if not is_admin(actor) and not lecturer_occurrence_allowed(offering, lecture_date, lecture_number):
        raise PermissionDenied('This lecture is not assigned or approved for this date.')
    reason = reason.strip()

    session = LectureSession.objects.select_for_update().filter(
        class_subject=offering,
        lecture_date=lecture_date,
        lecture_number=lecture_number,
    ).first()
    if not session and not lecturer_occurrence_allowed(offering, lecture_date, lecture_number):
        raise ValidationError('This class is not scheduled or approved for the selected date and lecture number.')
    if session and session.status == 'CANCELLED':
        return session, False
    if session and session.status == 'SUBMITTED' and not is_admin(actor):
        raise ValidationError('Attendance has already been submitted. Ask an administrator to correct the class status.')
    if session and session.status == 'SUBMITTED' and not reason:
        raise ValidationError('A reason is required when an administrator cancels a held class.')

    if not session:
        session = LectureSession.objects.create(
            class_subject=offering,
            lecture_date=lecture_date,
            lecture_number=lecture_number,
            status='CANCELLED',
            cancellation_reason=reason,
            submitted_by=actor,
        )
        return session, True

    # Admin correction: keep the original marks for audit/history, but they no
    # longer count because all attendance/fine queries require status=SUBMITTED.
    session.status = 'CANCELLED'
    session.cancellation_reason = reason
    session.submitted_by = actor
    session.save(update_fields=['status', 'cancellation_reason', 'submitted_by'])
    student_ids = list(session.records.values_list('student_id', flat=True))
    for sid in sorted(set(student_ids)):
        student = StudentProfile.objects.select_for_update().get(pk=sid)
        reconcile_fine(student, offering, actor=actor)
    return session, True


@transaction.atomic
def submit_attendance(*, actor, offering_id, lecture_date, lecture_number, present_ids, reason=''):
    """Create a held occurrence or edit existing marks; all mark edits are audited."""
    offering = ClassSubject.objects.select_for_update().select_related('class_group__term').get(pk=offering_id)
    if not can_write(actor, offering, lecture_date):
        raise PermissionDenied('Outside allowed date, hours or lecturer assignment.')
    if lecture_number < 1:
        raise ValidationError('Lecture number must be at least 1.')
    term = offering.term
    if not term or not (term.start_date <= lecture_date <= term.end_date):
        raise ValidationError('Lecture date is outside the academic term.')
    if not is_admin(actor) and not lecturer_occurrence_allowed(offering, lecture_date, lecture_number):
        raise PermissionDenied('This lecture is not assigned or approved for that date.')

    session = LectureSession.objects.filter(
        class_subject=offering, lecture_date=lecture_date, lecture_number=lecture_number,
    ).first()
    if session and session.status != 'SUBMITTED':
        raise ValidationError('Cancelled lectures cannot be marked as held. Ask an administrator if this was cancelled by mistake.')
    if session:
        records = list(AttendanceRecord.objects.select_for_update().filter(session=session).select_related('student'))
        roster = {r.student_id: r.student for r in records}
    else:
        linked_classes = list(offering.class_groups.values_list('pk', flat=True))
        if not linked_classes:
            linked_classes = [offering.class_group_id]
        roster = {s.pk: s for s in StudentProfile.objects.filter(
            memberships__class_group_id__in=linked_classes,
            memberships__term=term,
        ).distinct()}
        records = []
    if not roster:
        raise ValidationError('The class has no students. Import students first.')
    if not set(present_ids).issubset(roster):
        raise ValidationError('Invalid student ids were submitted.')
    new_marks = {student_id: ('P' if student_id in present_ids else 'A') for student_id in roster}
    old_marks = {r.student_id: r.status for r in records}
    changes = [(sid, old_marks.get(sid, ''), new_marks[sid]) for sid in roster if old_marks.get(sid, '') != new_marks[sid]]
    if session and changes and not reason.strip():
        raise ValidationError('A reason is required for attendance corrections.')
    if session and not changes:
        return session, 0
    if not session:
        session = LectureSession.objects.create(
            class_subject=offering, lecture_date=lecture_date, lecture_number=lecture_number,
            submitted_by=actor, status='SUBMITTED',
        )
    existing = {r.student_id: r for r in records}
    for sid, old, new in changes:
        record = existing.get(sid)
        if record:
            record.status = new
            record.save(update_fields=['status', 'updated_at'])
        else:
            record = AttendanceRecord.objects.create(session=session, student_id=sid, status=new)
        AttendanceAudit.objects.create(
            session=session, record=record, student_id=sid, actor=actor,
            action='EDIT' if old else 'CREATE', actor_role='ADMIN' if is_admin(actor) else 'LECTURER', old_status=old,
            new_status=new, reason=reason.strip() if old else '',
        )
    for sid in sorted(sid for sid, _, _ in changes):
        student = StudentProfile.objects.select_for_update().get(pk=sid)
        reconcile_fine(student, offering, actor=actor)
    return session, len(changes)


@transaction.atomic
def delete_held_session(*, actor, session_id, reason):
    """Permanently remove one Held session from operational attendance data.

    Only a Django superuser may perform this correction. Before the Held
    LectureSession, AttendanceRecord and per-mark AttendanceAudit rows are
    removed, an immutable SessionDeletionAudit snapshot is written. Fine
    balances are then reconciled from the remaining Held attendance.

    Removing the operational session intentionally makes the timetable
    occurrence Pending/Not Marked again (or an approved make-up unmarked), so
    it may be submitted again if the deletion corrected an accidental session.
    """
    if not actor.is_authenticated or not actor.is_active or not actor.is_superuser:
        raise PermissionDenied('Only the super admin can delete a held attendance session.')
    reason = (reason or '').strip()
    if not reason:
        raise ValidationError('A deletion reason is required.')

    # Lock in the same ClassSubject-first order used by submit_attendance so a
    # concurrent correction cannot race with the destructive part of deletion.
    initial = LectureSession.objects.select_related(
        'class_subject__subject', 'class_subject__class_group__term', 'submitted_by'
    ).filter(pk=session_id).first()
    if not initial:
        raise LectureSession.DoesNotExist
    offering = ClassSubject.objects.select_for_update().select_related(
        'subject', 'class_group__term'
    ).prefetch_related('class_groups').get(pk=initial.class_subject_id)
    session = LectureSession.objects.select_for_update().select_related('submitted_by').get(pk=session_id)
    if session.status != 'SUBMITTED':
        raise ValidationError('Only a Held session can be deleted.')

    records = list(AttendanceRecord.objects.select_for_update().filter(
        session=session
    ).select_related('student__user').order_by('student__user__username'))
    audits = list(AttendanceAudit.objects.select_for_update().filter(
        session=session
    ).select_related('actor', 'student__user').order_by('created_at', 'id'))

    record_snapshot = [{
        'record_id': record.pk,
        'student_id': record.student_id,
        'registration_number': record.student.user.username,
        'student_name': record.student.user.get_full_name() or record.student.user.username,
        'status': record.status,
        'status_label': record.get_status_display(),
        'updated_at': record.updated_at.isoformat() if record.updated_at else None,
    } for record in records]
    audit_snapshot = [{
        'audit_id': audit.pk,
        'record_id': audit.record_id,
        'student_id': audit.student_id,
        'registration_number': audit.student.user.username,
        'actor_id': audit.actor_id,
        'actor_username': audit.actor.username,
        'actor_role': audit.actor_role,
        'action': audit.action,
        'old_status': audit.old_status,
        'new_status': audit.new_status,
        'reason': audit.reason,
        'created_at': audit.created_at.isoformat() if audit.created_at else None,
    } for audit in audits]
    present_count = sum(record.status == AttendanceRecord.PRESENT for record in records)
    absent_count = sum(record.status == AttendanceRecord.ABSENT for record in records)

    deletion = SessionDeletionAudit.objects.create(
        original_session_id=session.pk,
        class_subject=offering,
        lecture_date=session.lecture_date,
        lecture_number=session.lecture_number,
        originally_submitted_by=session.submitted_by,
        originally_submitted_at=session.submitted_at,
        deleted_by=actor,
        reason=reason,
        record_count=len(records),
        present_count=present_count,
        absent_count=absent_count,
        snapshot={
            'subject': {'id': offering.subject_id, 'code': offering.subject.code, 'name': offering.subject.name},
            'classes': offering.class_codes_display,
            'section_code': offering.section_code,
            'records': record_snapshot,
            'attendance_audits': audit_snapshot,
        },
    )

    affected_student_ids = sorted({record.student_id for record in records})
    AttendanceAudit.objects.filter(session=session).delete()
    AttendanceRecord.objects.filter(session=session).delete()
    session.delete()

    for student_id in affected_student_ids:
        student = StudentProfile.objects.select_for_update().get(pk=student_id)
        reconcile_fine(student, offering, actor=actor)
    return deletion
