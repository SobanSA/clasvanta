from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from attendance.models import LectureSession
from .models import AcademicTerm, ClassGroup, ClassSubject, Programme, Subject


class DashboardLecturerDisplayTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.admin = User.objects.create_superuser(
            username='sohaib', password='Example123!',
            first_name='System', last_name='Administrator',
        )
        self.teacher = User.objects.create_user(
            username='T013', password='Example123!', role=User.Role.LECTURER,
            first_name='Ms. Rahat',
        )
        term = AcademicTerm.objects.create(
            name='Display Test Term', start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=60), is_active=True,
        )
        programme = Programme.objects.create(code='ADP-CS', name='ADP Computer Science')
        group = ClassGroup.objects.create(
            code='ADP-CS-I', programme=programme, term=term, semester_number=1,
        )
        subject = Subject.objects.create(
            code='CSSS1721', name='Basic Electronics-Lab', short_name='ELEC-L',
        )
        offering = ClassSubject.objects.create(
            class_group=group, subject=subject, lecturer=self.teacher,
        )
        offering.class_groups.add(group)
        self.session = LectureSession.objects.create(
            class_subject=offering, lecture_date=today, lecture_number=1,
            status='SUBMITTED', submitted_by=self.admin,
        )

    def test_recent_attendance_uses_assigned_lecturer_not_submitter(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ms. Rahat')
        self.assertNotContains(response, '<td>sohaib</td>', html=False)
        recent = list(response.context['recent_sessions'])
        self.assertEqual(recent[0].class_subject.lecturer, self.teacher)
        self.assertEqual(recent[0].submitted_by, self.admin)
