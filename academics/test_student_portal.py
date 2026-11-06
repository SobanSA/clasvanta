from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from attendance.models import MakeupClass
from attendance.services import cancel_class, create_makeup_class, review_makeup_class, submit_attendance
from fines.models import FinePolicy

from .models import (
    AcademicTerm, ClassGroup, ClassMembership, ClassSubject,
    Programme, StudentProfile, Subject, WeeklySchedule,
)


class StudentPortalV27Tests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.term = AcademicTerm.objects.create(
            name='Student Portal Test Term',
            start_date=self.today - timedelta(days=30),
            end_date=self.today + timedelta(days=60),
            is_active=True,
        )
        self.programme = Programme.objects.create(code='BS-TST', name='Portal Testing')
        self.class_a = ClassGroup.objects.create(
            code='TST-A', name='Semester 1 A', programme=self.programme,
            term=self.term, semester_number=1,
        )
        self.class_b = ClassGroup.objects.create(
            code='TST-B', name='Semester 1 B', programme=self.programme,
            term=self.term, semester_number=1,
        )
        self.teacher = User.objects.create_user(
            username='TCH-PORTAL', password='Example123!', role=User.Role.LECTURER,
            first_name='Portal Teacher',
        )
        self.admin = User.objects.create_superuser(
            username='admin-portal', password='Example123!',
        )
        self.student_user = User.objects.create_user(
            username='REG-001', password='Example123!', role=User.Role.STUDENT,
            first_name='Primary Student',
        )
        self.other_user = User.objects.create_user(
            username='REG-SECRET-002', password='Example123!', role=User.Role.STUDENT,
            first_name='Other Student Secret',
        )
        self.student = StudentProfile.objects.create(user=self.student_user)
        self.other_student = StudentProfile.objects.create(user=self.other_user)
        ClassMembership.objects.create(
            student=self.student, term=self.term, class_group=self.class_a,
        )
        ClassMembership.objects.create(
            student=self.other_student, term=self.term, class_group=self.class_b,
        )

        self.subject = Subject.objects.create(
            code='MAT-101', name='Applied Mathematics', short_name='Math',
        )
        self.offering = ClassSubject.objects.create(
            class_group=self.class_a, subject=self.subject, lecturer=self.teacher,
        )
        self.offering.class_groups.add(self.class_a, self.class_b)
        self.schedule = WeeklySchedule.objects.create(
            class_subject=self.offering,
            weekday=self.today.weekday(),
            lecture_number=1,
        )
        FinePolicy.objects.create(
            term=self.term,
            allowed_absences=1,
            rate_per_extra_absence=Decimal('100.00'),
        )

    def _subject_row(self, response, code='MAT-101'):
        return next(row for row in response.context['subjects'] if row['offering'].subject.code == code)

    def test_student_routes_are_self_scoped_and_admin_actions_are_forbidden(self):
        self.client.force_login(self.student_user)
        for url_name in ('dashboard', 'student_my_attendance', 'student_schedule', 'student_fines', 'student_profile'):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200, url_name)

        # Supplying another student's id is ignored because student routes never accept a selector.
        response = self.client.get(reverse('student_my_attendance'), {'student': self.other_student.pk})
        self.assertEqual(response.context['profile'].pk, self.student.pk)
        self.assertNotContains(response, self.other_user.username)
        self.assertNotContains(response, 'Other Student Secret')

        self.assertEqual(self.client.get(reverse('students_list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('lecturer_dashboard')).status_code, 403)
        self.assertEqual(self.client.get(reverse('fines_dashboard')).status_code, 403)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('student_my_attendance')).status_code, 403)

    def test_pending_and_cancelled_are_excluded_but_held_counts(self):
        self.client.force_login(self.student_user)
        response = self.client.get(reverse('student_my_attendance'))
        row = self._subject_row(response)
        self.assertEqual(row['total'], 0)  # Weekly schedule alone is Pending, not Held.

        cancel_class(
            actor=self.admin,
            offering_id=self.offering.pk,
            lecture_date=self.today,
            lecture_number=1,
        )
        response = self.client.get(reverse('student_my_attendance'))
        self.assertEqual(self._subject_row(response)['total'], 0)
        schedule_response = self.client.get(reverse('student_schedule'))
        self.assertEqual(schedule_response.context['rows'][0]['state'], 'CANCELLED')

        yesterday = self.today - timedelta(days=1)
        submit_attendance(
            actor=self.admin,
            offering_id=self.offering.pk,
            lecture_date=yesterday,
            lecture_number=2,
            present_ids={self.student.pk, self.other_student.pk},
        )
        response = self.client.get(reverse('student_my_attendance'))
        row = self._subject_row(response)
        self.assertEqual(row['total'], 1)
        self.assertEqual(row['present'], 1)
        self.assertEqual(row['percentage'], 100.0)

    def test_approved_makeup_is_visible_but_counts_only_after_attendance_submission(self):
        makeup = create_makeup_class(
            actor=self.teacher,
            offering_id=self.offering.pk,
            lecture_date=self.today,
            lecture_number=2,
            note='Portal make-up test',
        )
        self.assertEqual(makeup.status, MakeupClass.PENDING)

        self.client.force_login(self.student_user)
        schedule_response = self.client.get(reverse('student_schedule'))
        self.assertFalse(any(row['source'] == 'MAKEUP' for row in schedule_response.context['rows']))
        self.assertEqual(self._subject_row(self.client.get(reverse('student_my_attendance')))['total'], 0)

        review_makeup_class(actor=self.admin, makeup_id=makeup.pk, approve=True)
        schedule_response = self.client.get(reverse('student_schedule'))
        makeup_rows = [row for row in schedule_response.context['rows'] if row['source'] == 'MAKEUP']
        self.assertEqual(len(makeup_rows), 1)
        self.assertEqual(makeup_rows[0]['state'], 'SCHEDULED')
        self.assertEqual(self._subject_row(self.client.get(reverse('student_my_attendance')))['total'], 0)

        submit_attendance(
            actor=self.admin,
            offering_id=self.offering.pk,
            lecture_date=self.today,
            lecture_number=2,
            present_ids={self.student.pk},
        )
        response = self.client.get(reverse('student_my_attendance'))
        row = self._subject_row(response)
        self.assertEqual(row['total'], 1)
        self.assertEqual(row['present'], 1)
        self.assertEqual(row['history'][0]['source'], 'Make-up')

    def test_fine_page_uses_ledger_and_admin_correction_is_reflected(self):
        yesterday = self.today - timedelta(days=1)
        submit_attendance(
            actor=self.admin,
            offering_id=self.offering.pk,
            lecture_date=yesterday,
            lecture_number=3,
            present_ids={self.other_student.pk},
        )
        second_session, _ = submit_attendance(
            actor=self.admin,
            offering_id=self.offering.pk,
            lecture_date=self.today,
            lecture_number=4,
            present_ids={self.other_student.pk},
        )

        self.client.force_login(self.student_user)
        response = self.client.get(reverse('student_fines'))
        row = response.context['rows'][0]
        self.assertEqual(row['absent'], 2)
        self.assertEqual(row['excess_absences'], 1)
        self.assertEqual(row['gross_target'], Decimal('100.00'))
        self.assertEqual(row['fine_balance'], Decimal('100.00'))
        self.assertEqual(sum(1 for item in row['absence_history'] if item['chargeable']), 1)

        submit_attendance(
            actor=self.admin,
            offering_id=self.offering.pk,
            lecture_date=second_session.lecture_date,
            lecture_number=second_session.lecture_number,
            present_ids={self.student.pk, self.other_student.pk},
            reason='Verified attendance correction',
        )
        response = self.client.get(reverse('student_fines'))
        row = response.context['rows'][0]
        self.assertEqual(row['absent'], 1)
        self.assertEqual(row['excess_absences'], 0)
        self.assertEqual(row['fine_balance'], Decimal('0.00'))

    def test_merged_and_legacy_subject_sections_are_visible_to_correct_student(self):
        legacy_subject = Subject.objects.create(
            code='LEG-201', name='Legacy Linked Subject', short_name='Legacy',
        )
        # Deliberately leave class_groups empty to exercise the primary-class fallback.
        ClassSubject.objects.create(
            class_group=self.class_b,
            subject=legacy_subject,
            lecturer=self.teacher,
        )

        self.client.force_login(self.other_user)
        response = self.client.get(reverse('student_my_attendance'))
        codes = {row['offering'].subject.code for row in response.context['subjects']}
        self.assertIn('MAT-101', codes)  # merged section includes class B
        self.assertIn('LEG-201', codes)  # legacy primary-class fallback

        self.client.force_login(self.student_user)
        response = self.client.get(reverse('student_my_attendance'))
        codes = {row['offering'].subject.code for row in response.context['subjects']}
        self.assertIn('MAT-101', codes)
        self.assertNotIn('LEG-201', codes)

    def test_date_schedule_and_profile_are_read_only(self):
        tomorrow = self.today + timedelta(days=1)
        WeeklySchedule.objects.create(
            class_subject=self.offering,
            weekday=tomorrow.weekday(),
            lecture_number=5,
        )
        self.client.force_login(self.student_user)
        response = self.client.get(reverse('student_schedule'), {'date': tomorrow.isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_date'], tomorrow)
        self.assertTrue(any(row['lecture_number'] == 5 for row in response.context['rows']))

        profile_response = self.client.get(reverse('student_profile'))
        self.assertContains(profile_response, self.programme.name)
        self.assertContains(profile_response, self.class_a.code)
        self.assertContains(profile_response, self.term.name)
        self.assertEqual(self.client.post(reverse('student_profile'), {'class': self.class_b.pk}).status_code, 405)

    def test_dashboard_backward_compatible_context_and_held_only_math(self):
        submit_attendance(
            actor=self.admin,
            offering_id=self.offering.pk,
            lecture_date=self.today,
            lecture_number=2,
            present_ids={self.student.pk},
        )
        self.client.force_login(self.student_user)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        row = self._subject_row(response)
        self.assertEqual(row['present'], 1)
        self.assertEqual(row['total'], 1)
        self.assertEqual(row['allowed_remaining'], 1)
        self.assertEqual(row['fine_balance'], Decimal('0.00'))
        self.assertIn('today_schedule', response.context)
