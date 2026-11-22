from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from attendance.models import AttendanceAudit, AttendanceRecord, LectureSession, SessionDeletionAudit
from fines.models import FineLedgerEntry
from .models import AcademicTerm, ClassGroup, ClassMembership, ClassSubject, Programme, StudentProfile, Subject


class StudentDeletionTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.term = AcademicTerm.objects.create(name='Deletion Test', start_date=today, end_date=today, is_active=True)
        self.programme = Programme.objects.create(code='DEL', name='Deletion')
        self.group = ClassGroup.objects.create(code='DEL-A', programme=self.programme, term=self.term, semester_number=1)
        self.admin = User.objects.create_user(username='DEL-ADMIN', password='x', role=User.Role.ADMIN)
        self.student_user = User.objects.create_user(username='DEL-001', password='x', role=User.Role.STUDENT, first_name='Delete Me')
        self.student = StudentProfile.objects.create(user=self.student_user)
        ClassMembership.objects.create(student=self.student, term=self.term, class_group=self.group)

    def _history(self):
        subject = Subject.objects.create(code='DEL-101', name='Deletion Subject', short_name='DEL')
        offering = ClassSubject.objects.create(class_group=self.group, subject=subject)
        offering.class_groups.add(self.group)
        session = LectureSession.objects.create(
            class_subject=offering,
            lecture_date=self.term.start_date,
            lecture_number=1,
            status='SUBMITTED',
            submitted_by=self.admin,
        )
        record = AttendanceRecord.objects.create(session=session, student=self.student, status='A')
        AttendanceAudit.objects.create(
            session=session, record=record, student=self.student, actor=self.admin,
            action='CREATE', actor_role='ADMIN', old_status='', new_status='A', reason='',
        )
        FineLedgerEntry.objects.create(
            student=self.student, class_subject=offering, kind='CHARGE', amount=Decimal('100.00'),
            note='Force-delete test', actor=self.admin,
        )
        deletion = SessionDeletionAudit.objects.create(
            original_session_id=999999,
            class_subject=offering,
            lecture_date=self.term.start_date,
            lecture_number=1,
            originally_submitted_by=self.admin,
            originally_submitted_at=session.submitted_at,
            deleted_by=self.admin,
            reason='Snapshot test',
            record_count=1,
            present_count=0,
            absent_count=1,
            snapshot={
                'records': [{
                    'student_id': self.student.pk,
                    'registration_number': self.student_user.username,
                    'status': 'A',
                }],
                'attendance_audits': [{
                    'student_id': self.student.pk,
                    'registration_number': self.student_user.username,
                }],
            },
        )
        return session, record, deletion

    def test_admin_can_deactivate_and_reactivate_student(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('student_delete', args=[self.student.pk]), {'action': 'toggle_active'}
        )
        self.assertRedirects(response, reverse('student_delete', args=[self.student.pk]))
        self.student_user.refresh_from_db()
        self.assertFalse(self.student_user.is_active)

        self.client.post(reverse('student_delete', args=[self.student.pk]), {'action': 'toggle_active'})
        self.student_user.refresh_from_db()
        self.assertTrue(self.student_user.is_active)

    def test_admin_can_safe_delete_student_without_history(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('student_delete', args=[self.student.pk]),
            {'action': 'safe_delete', 'confirm_registration': 'DEL-001'},
        )
        self.assertRedirects(response, reverse('students_list'))
        self.assertFalse(User.objects.filter(pk=self.student_user.pk).exists())
        self.assertFalse(StudentProfile.objects.filter(pk=self.student.pk).exists())

    def test_safe_delete_still_blocks_history(self):
        self._history()
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('student_delete', args=[self.student.pk]),
            {'action': 'safe_delete', 'confirm_registration': 'DEL-001'},
        )
        self.assertRedirects(response, reverse('student_delete', args=[self.student.pk]))
        self.assertTrue(StudentProfile.objects.filter(pk=self.student.pk).exists())

    def test_force_delete_requires_exact_phrase(self):
        self._history()
        self.client.force_login(self.admin)
        self.client.post(
            reverse('student_delete', args=[self.student.pk]),
            {'action': 'force_delete', 'confirm_registration': 'DEL-001', 'confirm_phrase': 'DELETE'},
        )
        self.assertTrue(StudentProfile.objects.filter(pk=self.student.pk).exists())

    def test_force_delete_wipes_student_history_and_fines(self):
        _, _, deletion = self._history()
        student_id = self.student.pk
        user_id = self.student_user.pk
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('student_delete', args=[student_id]),
            {
                'action': 'force_delete',
                'confirm_registration': 'DEL-001',
                'confirm_phrase': 'FORCE DELETE',
            },
        )
        self.assertRedirects(response, reverse('students_list'))
        self.assertFalse(User.objects.filter(pk=user_id).exists())
        self.assertFalse(StudentProfile.objects.filter(pk=student_id).exists())
        self.assertFalse(ClassMembership.objects.filter(student_id=student_id).exists())
        self.assertFalse(AttendanceRecord.objects.filter(student_id=student_id).exists())
        self.assertFalse(AttendanceAudit.objects.filter(student_id=student_id).exists())
        self.assertFalse(FineLedgerEntry.objects.filter(student_id=student_id).exists())

        deletion.refresh_from_db()
        self.assertEqual(deletion.record_count, 0)
        self.assertEqual(deletion.present_count, 0)
        self.assertEqual(deletion.absent_count, 0)
        self.assertEqual(deletion.snapshot.get('records'), [])
        self.assertEqual(deletion.snapshot.get('attendance_audits'), [])
