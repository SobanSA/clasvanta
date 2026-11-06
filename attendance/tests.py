from datetime import timedelta
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from academics.models import (
    AcademicTerm, ClassGroup, ClassMembership, ClassSubject,
    Programme, StudentProfile, Subject, WeeklySchedule,
)
from fines.models import FineLedgerEntry, FinePolicy
from .models import AttendanceAudit, AttendanceRecord, AttendanceSettings, LectureSession, MakeupClass, SessionDeletionAudit
from .services import submit_attendance, can_write, cancel_class, create_makeup_class, review_makeup_class, delete_held_session


class LecturerAttendanceWorkflowTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.term = AcademicTerm.objects.create(
            name='Workflow Test Term', start_date=self.today - timedelta(days=40),
            end_date=self.today + timedelta(days=40), is_active=True,
        )
        self.programme = Programme.objects.create(code='TEST', name='Testing')
        self.class1 = ClassGroup.objects.create(
            code='TEST-A', programme=self.programme, term=self.term, semester_number=1,
        )
        self.class2 = ClassGroup.objects.create(
            code='TEST-B', programme=self.programme, term=self.term, semester_number=1,
        )
        self.teacher = User.objects.create_user(
            username='TCH101', password='Example123!', role=User.Role.LECTURER,
        )
        self.admin = User.objects.create_superuser(username='admin', password='Example123!')
        self.students = []
        for n, group in enumerate((self.class1, self.class2), start=1):
            account = User.objects.create_user(
                username=f'STU{n}', password='Example123!', role=User.Role.STUDENT,
            )
            profile = StudentProfile.objects.create(user=account)
            ClassMembership.objects.create(student=profile, class_group=group, term=self.term)
            self.students.append(profile)
        self.subject = Subject.objects.create(code='ENG', name='English', short_name='English')
        self.section = ClassSubject.objects.create(
            class_group=self.class1, subject=self.subject, lecturer=self.teacher,
        )
        self.section.class_groups.add(self.class1, self.class2)
        self.schedule = WeeklySchedule.objects.create(
            class_subject=self.section, weekday=self.today.weekday(), lecture_number=1,
        )
        AttendanceSettings.objects.create(pk=1, working_start='00:00', working_end='23:59:59')
        FinePolicy.objects.create(
            term=self.term, allowed_absences=0, rate_per_extra_absence=Decimal('150.00'),
        )

    def test_merged_roster_single_submission_audit_and_fine_reversal(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('lecturer_dashboard'))
        self.assertEqual(response.status_code, 200)
        lecture = response.context['lectures'][0]
        self.assertEqual(lecture['student_count'], 2)
        self.assertTrue(lecture['merged'])

        response = self.client.post(reverse('mark_schedule', args=[self.schedule.pk]), {
            'present_ids': [str(self.students[0].pk)],
        })
        self.assertEqual(response.status_code, 302)
        session = LectureSession.objects.get(class_subject=self.section)
        self.assertEqual(AttendanceRecord.objects.filter(session=session).count(), 2)
        self.assertEqual(AttendanceAudit.objects.filter(session=session, action='CREATE').count(), 2)
        self.assertEqual(FineLedgerEntry.objects.filter(
            student=self.students[1], class_subject=self.section,
        ).aggregate(s=Sum('amount'))['s'], Decimal('150.00'))

        # Posting unchanged marks does not duplicate initial submissions or fines.
        self.client.post(reverse('session_detail', args=[session.pk]), {
            'present_ids': [str(self.students[0].pk)],
        })
        self.assertEqual(AttendanceAudit.objects.filter(session=session).count(), 2)

        self.client.force_login(self.admin)
        response = self.client.post(reverse('session_detail', args=[session.pk]), {
            'present_ids': [str(self.students[0].pk), str(self.students[1].pk)],
            'reason': 'Admin verified the attendance register',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AttendanceAudit.objects.filter(session=session, action='EDIT').count(), 1)
        correction = AttendanceAudit.objects.get(session=session, action='EDIT')
        self.assertEqual((correction.old_status, correction.new_status), ('A', 'P'))
        self.assertEqual(correction.actor_id, self.admin.pk)
        self.assertEqual(FineLedgerEntry.objects.filter(
            student=self.students[1], class_subject=self.section,
        ).aggregate(s=Sum('amount'))['s'], Decimal('0.00'))

    def test_warnings_include_absences_from_other_lectures(self):
        other_subject = Subject.objects.create(code='CS', name='Computer Science', short_name='CS')
        other_section = ClassSubject.objects.create(
            class_group=self.class1, subject=other_subject, lecturer=self.teacher,
        )
        other_section.class_groups.add(self.class1)
        other_schedule = WeeklySchedule.objects.create(
            class_subject=other_section, weekday=self.today.weekday(), lecture_number=2,
        )
        submit_attendance(actor=self.admin, offering_id=self.section.pk,
                          lecture_date=self.today, lecture_number=1, present_ids=set())
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('mark_schedule', args=[other_schedule.pk]))
        self.assertEqual(response.status_code, 200)
        student = next(item for item in response.context['roster'] if item['student'] == self.students[0])
        self.assertEqual(student['warnings'], 1)

    def test_lecturer_cannot_backdate_but_admin_can(self):
        yesterday = self.today - timedelta(days=1)
        self.assertFalse(can_write(self.teacher, self.section, yesterday))
        with self.assertRaises(PermissionDenied):
            submit_attendance(actor=self.teacher, offering_id=self.section.pk,
                              lecture_date=yesterday, lecture_number=1, present_ids=set())
        session, changes = submit_attendance(
            actor=self.admin, offering_id=self.section.pk, lecture_date=yesterday,
            lecture_number=1, present_ids=set(),
        )
        self.assertEqual(changes, 2)
        self.assertEqual(session.lecture_date, yesterday)

    def test_clashes_are_rejected(self):
        other_subject = Subject.objects.create(code='CS', name='Computer Science', short_name='CS')
        other_section = ClassSubject.objects.create(
            class_group=self.class2, subject=other_subject, lecturer=self.teacher,
        )
        other_section.class_groups.add(self.class2)
        clash = WeeklySchedule(
            class_subject=other_section, weekday=self.today.weekday(), lecture_number=1,
        )
        with self.assertRaises(ValidationError):
            clash.full_clean()
        other_teacher = User.objects.create_user(
            'TCH102', password='Example123!', role=User.Role.LECTURER,
        )
        other_section.lecturer = other_teacher
        other_section.class_groups.add(self.class1)
        with self.assertRaises(ValidationError):
            clash.full_clean()

    def test_student_sees_allowed_absences_remaining_and_fine_due(self):
        self.client.force_login(self.students[0].user)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['subjects'][0]['allowed_remaining'], 0)
        self.assertEqual(response.context['subjects'][0]['fine_balance'], Decimal('0.00'))


class MakeupAndClassStatusTests(LecturerAttendanceWorkflowTests):
    def test_unmarked_and_cancelled_classes_do_not_count_as_held(self):
        # A timetable row by itself is Pending and creates no held-class total.
        self.client.force_login(self.admin)
        response = self.client.get(reverse('student_attendance') + f'?student={self.students[0].pk}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['subject_rows'][0]['total'], 0)

        cancel_class(
            actor=self.teacher, offering_id=self.section.pk,
            lecture_date=self.today, lecture_number=1,
        )
        session = LectureSession.objects.get(class_subject=self.section, lecture_date=self.today, lecture_number=1)
        self.assertEqual(session.status, 'CANCELLED')
        self.assertEqual(AttendanceRecord.objects.filter(session=session).count(), 0)

        response = self.client.get(reverse('student_attendance') + f'?student={self.students[0].pk}')
        self.assertEqual(response.context['subject_rows'][0]['total'], 0)

    def test_lecturer_makeup_requires_superuser_approval_before_attendance(self):
        makeup = create_makeup_class(
            actor=self.teacher, offering_id=self.section.pk,
            lecture_date=self.today, lecture_number=2,
            note='Replacement class',
        )
        self.assertEqual(makeup.status, MakeupClass.PENDING)

        with self.assertRaises(PermissionDenied):
            submit_attendance(
                actor=self.teacher, offering_id=self.section.pk,
                lecture_date=self.today, lecture_number=2,
                present_ids={self.students[0].pk, self.students[1].pk},
            )

        regular_admin = User.objects.create_user(
            username='ADMIN2', password='Example123!', role=User.Role.ADMIN,
        )
        with self.assertRaises(PermissionDenied):
            review_makeup_class(actor=regular_admin, makeup_id=makeup.pk, approve=True)

        makeup = review_makeup_class(actor=self.admin, makeup_id=makeup.pk, approve=True)
        self.assertEqual(makeup.status, MakeupClass.APPROVED)
        session, changes = submit_attendance(
            actor=self.teacher, offering_id=self.section.pk,
            lecture_date=self.today, lecture_number=2,
            present_ids={self.students[0].pk, self.students[1].pk},
        )
        self.assertEqual(session.status, 'SUBMITTED')
        self.assertEqual(changes, 2)

    def test_lecturer_can_request_only_assigned_subjects(self):
        other_teacher = User.objects.create_user(
            username='TCH999', password='Example123!', role=User.Role.LECTURER,
        )
        with self.assertRaises(PermissionDenied):
            create_makeup_class(
                actor=other_teacher, offering_id=self.section.pk,
                lecture_date=self.today, lecture_number=2,
            )

    def test_admin_arranged_makeup_is_immediately_approved(self):
        makeup = create_makeup_class(
            actor=self.admin, offering_id=self.section.pk,
            lecture_date=self.today, lecture_number=2,
        )
        self.assertEqual(makeup.status, MakeupClass.APPROVED)
        self.assertEqual(makeup.reviewed_by, self.admin)

    def test_approved_makeup_appears_on_lecturer_dashboard(self):
        makeup = create_makeup_class(
            actor=self.admin, offering_id=self.section.pk,
            lecture_date=self.today, lecture_number=2,
        )
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('lecturer_dashboard'))
        self.assertEqual(response.status_code, 200)
        rows = response.context['lectures']
        self.assertTrue(any(row['source'] == 'MAKEUP' and row['makeup'].pk == makeup.pk for row in rows))

    def test_student_drilldown_counts_only_held_classes(self):
        makeup = create_makeup_class(
            actor=self.admin, offering_id=self.section.pk,
            lecture_date=self.today, lecture_number=2,
        )
        submit_attendance(
            actor=self.teacher, offering_id=self.section.pk,
            lecture_date=self.today, lecture_number=2,
            present_ids={self.students[0].pk},
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse('student_attendance') + f'?student={self.students[0].pk}')
        row = response.context['subject_rows'][0]
        self.assertEqual(row['present'], 1)
        self.assertEqual(row['total'], 1)
        self.assertEqual(len(row['history']), 1)


class HeldSessionDeletionTests(LecturerAttendanceWorkflowTests):
    def _held_session_with_absence(self):
        session, _ = submit_attendance(
            actor=self.admin, offering_id=self.section.pk, lecture_date=self.today,
            lecture_number=1, present_ids={self.students[0].pk},
        )
        return session

    def test_only_superuser_can_delete_held_session(self):
        session = self._held_session_with_absence()
        regular_admin = User.objects.create_user(
            username='ADMIN-REGULAR', password='Example123!', role=User.Role.ADMIN,
        )
        self.client.force_login(regular_admin)
        response = self.client.get(reverse('delete_session', args=[session.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(LectureSession.objects.filter(pk=session.pk).exists())

        with self.assertRaises(PermissionDenied):
            delete_held_session(
                actor=regular_admin, session_id=session.pk, reason='Should not be allowed',
            )

    def test_superuser_delete_restores_pending_reconciles_fine_and_keeps_snapshot(self):
        session = self._held_session_with_absence()
        session_id = session.pk
        self.assertEqual(
            FineLedgerEntry.objects.filter(
                student=self.students[1], class_subject=self.section,
            ).aggregate(s=Sum('amount'))['s'],
            Decimal('150.00'),
        )
        self.assertEqual(AttendanceAudit.objects.filter(session=session).count(), 2)

        self.client.force_login(self.admin)
        response = self.client.post(reverse('delete_session', args=[session.pk]), {
            'reason': 'Attendance was submitted against the wrong session',
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(LectureSession.objects.filter(pk=session_id).exists())
        self.assertFalse(AttendanceRecord.objects.filter(session_id=session_id).exists())
        self.assertFalse(AttendanceAudit.objects.filter(session_id=session_id).exists())

        deletion = SessionDeletionAudit.objects.get(original_session_id=session_id)
        self.assertEqual(deletion.deleted_by, self.admin)
        self.assertEqual(deletion.record_count, 2)
        self.assertEqual(deletion.present_count, 1)
        self.assertEqual(deletion.absent_count, 1)
        self.assertEqual(deletion.reason, 'Attendance was submitted against the wrong session')
        self.assertEqual(len(deletion.snapshot['records']), 2)
        self.assertEqual(len(deletion.snapshot['attendance_audits']), 2)

        # The old charge remains in the append-only ledger, with an automatic
        # reversal so the current balance becomes zero.
        self.assertEqual(
            FineLedgerEntry.objects.filter(
                student=self.students[1], class_subject=self.section,
            ).aggregate(s=Sum('amount'))['s'],
            Decimal('0.00'),
        )

        response = self.client.get(reverse('admin_sessions') + f'?date={self.today.isoformat()}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['held_count'], 0)
        self.assertEqual(response.context['pending_count'], 1)
        row = response.context['schedule_rows'][0]
        self.assertIsNone(row['session'])

        # Because this is a deletion rather than a cancellation, the occurrence
        # can be submitted again normally.
        replacement, changes = submit_attendance(
            actor=self.admin, offering_id=self.section.pk, lecture_date=self.today,
            lecture_number=1, present_ids={student.pk for student in self.students},
        )
        self.assertNotEqual(replacement.pk, session_id)
        self.assertEqual(changes, 2)
        self.assertEqual(replacement.status, 'SUBMITTED')

    def test_deletion_requires_reason_and_only_accepts_held_session(self):
        session = self._held_session_with_absence()
        with self.assertRaises(ValidationError):
            delete_held_session(actor=self.admin, session_id=session.pk, reason='')
        self.assertTrue(LectureSession.objects.filter(pk=session.pk).exists())

        # A cancelled occurrence is history, not a Held session, so the delete
        # function refuses it.
        cancel_session = LectureSession.objects.create(
            class_subject=self.section, lecture_date=self.today + timedelta(days=1),
            lecture_number=2, submitted_by=self.admin, status='CANCELLED',
            cancellation_reason='No class',
        )
        with self.assertRaises(ValidationError):
            delete_held_session(
                actor=self.admin, session_id=cancel_session.pk, reason='Try to remove cancellation',
            )
        self.assertTrue(LectureSession.objects.filter(pk=cancel_session.pk).exists())

    def test_deletion_is_visible_in_audit_log(self):
        session = self._held_session_with_absence()
        delete_held_session(
            actor=self.admin, session_id=session.pk, reason='Duplicate held session',
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse('audit_log') + '?action=DELETE')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['deletions']), 1)
        self.assertContains(response, 'Duplicate held session')
