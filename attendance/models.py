from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class AttendanceSettings(models.Model):
    # A single record with pk=1 holds the institute-wide working hours.
    working_start = models.TimeField(default='08:00')
    working_end = models.TimeField(default='16:00')

    def clean(self):
        if self.working_start and self.working_end and self.working_start >= self.working_end:
            raise ValidationError('Working hours must end after they begin (same day).')

    def __str__(self):
        return 'Attendance working hours'


class MakeupClass(models.Model):
    """One-off lecture outside the recurring weekly timetable.

    Lecturer-created rows require super-admin approval. Admin-created rows can be
    approved immediately by the custom workflow. Attendance can only be submitted
    for approved rows.
    """
    PENDING = 'PENDING'
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'
    STATUS = [
        (PENDING, 'Pending approval'),
        (APPROVED, 'Approved'),
        (REJECTED, 'Rejected'),
    ]

    class_subject = models.ForeignKey(
        'academics.ClassSubject', on_delete=models.PROTECT, related_name='makeup_classes'
    )
    lecture_date = models.DateField(db_index=True)
    lecture_number = models.PositiveSmallIntegerField()
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='makeup_requests'
    )
    request_note = models.CharField(max_length=400, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default=PENDING, db_index=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='reviewed_makeup_requests', null=True, blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=400, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-lecture_date', 'lecture_number', '-created_at']

    def clean(self):
        if self.lecture_number is not None and not (1 <= self.lecture_number <= 20):
            raise ValidationError('Lecture number must be between 1 and 20.')
        if self.class_subject_id:
            term = self.class_subject.term
            if term and self.lecture_date and not (term.start_date <= self.lecture_date <= term.end_date):
                raise ValidationError('Make-up class date is outside the academic term.')

    def __str__(self):
        return f'{self.class_subject} / {self.lecture_date} L{self.lecture_number} / {self.get_status_display()}'


class LectureSession(models.Model):
    class_subject = models.ForeignKey('academics.ClassSubject', on_delete=models.PROTECT, related_name='lecture_sessions')
    lecture_date = models.DateField()
    lecture_number = models.PositiveSmallIntegerField()
    STATUS = [('SUBMITTED', 'Held'), ('CANCELLED', 'Cancelled')]
    status = models.CharField(max_length=12, choices=STATUS, default='SUBMITTED')
    cancellation_reason = models.CharField(max_length=400, blank=True, default='')
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='submitted_sessions')
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-lecture_date', 'lecture_number']
        constraints = [models.UniqueConstraint(fields=['class_subject', 'lecture_date', 'lecture_number'], name='unique_lecture_occurrence')]

    def __str__(self):
        return f'{self.class_subject} / {self.lecture_date} L{self.lecture_number}'


class SessionDeletionAudit(models.Model):
    """Immutable snapshot created when a super admin deletes a Held session.

    The operational LectureSession/AttendanceRecord rows can then be removed so
    the timetable occurrence returns to Pending, while the accountability trail
    remains available independently of those deleted foreign keys.
    """
    original_session_id = models.PositiveBigIntegerField(db_index=True)
    class_subject = models.ForeignKey(
        'academics.ClassSubject', on_delete=models.PROTECT, related_name='session_deletion_audits'
    )
    lecture_date = models.DateField(db_index=True)
    lecture_number = models.PositiveSmallIntegerField()
    originally_submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='originally_submitted_deleted_sessions'
    )
    originally_submitted_at = models.DateTimeField()
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='deleted_attendance_sessions'
    )
    reason = models.CharField(max_length=400)
    record_count = models.PositiveIntegerField(default=0)
    present_count = models.PositiveIntegerField(default=0)
    absent_count = models.PositiveIntegerField(default=0)
    snapshot = models.JSONField(default=dict)
    deleted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-deleted_at', '-id']

    def __str__(self):
        return f'Deleted session #{self.original_session_id} / {self.lecture_date} L{self.lecture_number}'


class AttendanceRecord(models.Model):
    PRESENT = 'P'
    ABSENT = 'A'
    STATUS = [(PRESENT, 'Present'), (ABSENT, 'Absent')]
    session = models.ForeignKey(LectureSession, on_delete=models.PROTECT, related_name='records')
    student = models.ForeignKey('academics.StudentProfile', on_delete=models.PROTECT, related_name='attendance_records')
    status = models.CharField(max_length=1, choices=STATUS)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['session', 'student'], name='one_mark_per_student_lecture')]


class AttendanceAudit(models.Model):
    ACTIONS = [('CREATE', 'Initial submission'), ('EDIT', 'Correction')]
    session = models.ForeignKey(LectureSession, on_delete=models.PROTECT, related_name='audit_logs')
    record = models.ForeignKey(AttendanceRecord, on_delete=models.PROTECT, related_name='audit_logs')
    student = models.ForeignKey('academics.StudentProfile', on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=8, choices=ACTIONS)
    actor_role = models.CharField(max_length=12, blank=True, default='', help_text='Role captured when the action occurred')
    old_status = models.CharField(max_length=1, blank=True)
    new_status = models.CharField(max_length=1, choices=AttendanceRecord.STATUS)
    reason = models.CharField(max_length=400, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.actor} / {self.get_action_display()} / {self.student}'
