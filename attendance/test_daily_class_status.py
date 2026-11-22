from calendar import monthrange
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from academics.models import AcademicTerm, ClassGroup, ClassSubject, Programme, Subject, WeeklySchedule
from attendance.models import LectureSession, MakeupClass


class DailyClassStatusTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.term = AcademicTerm.objects.create(
            name='Daily Status Test Term',
            start_date=self.today - timedelta(days=10),
            end_date=self.today + timedelta(days=10),
            is_active=True,
        )
        self.programme = Programme.objects.create(code='DST', name='Daily Status')
        self.group = ClassGroup.objects.create(
            code='DST-A', programme=self.programme, term=self.term, semester_number=1,
        )
        self.teacher = User.objects.create_user(
            username='DST-T', password='Example123!', role=User.Role.LECTURER,
        )
        self.admin = User.objects.create_superuser('dst-admin', password='Example123!')
        self.subject1 = Subject.objects.create(code='DST-1', name='Held Subject', short_name='Held')
        self.subject2 = Subject.objects.create(code='DST-2', name='Pending Subject', short_name='Pending')
        self.offering1 = ClassSubject.objects.create(
            class_group=self.group, subject=self.subject1, lecturer=self.teacher,
        )
        self.offering2 = ClassSubject.objects.create(
            class_group=self.group, subject=self.subject2, lecturer=self.teacher,
        )
        self.offering1.class_groups.add(self.group)
        self.offering2.class_groups.add(self.group)
        WeeklySchedule.objects.create(
            class_subject=self.offering1, weekday=self.today.weekday(), lecture_number=1,
        )
        WeeklySchedule.objects.create(
            class_subject=self.offering2, weekday=self.today.weekday(), lecture_number=2,
        )
        LectureSession.objects.create(
            class_subject=self.offering1, lecture_date=self.today, lecture_number=1,
            status='SUBMITTED', submitted_by=self.admin,
        )

    def test_today_screen_shows_held_and_pending(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_sessions'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_date'], self.today)
        self.assertEqual(response.context['scheduled_count'], 2)
        self.assertEqual(response.context['held_count'], 1)
        self.assertEqual(response.context['unmarked_count'], 1)
        self.assertEqual(response.context['unmarked_label'], 'Pending')
        states = {row['state'] for row in response.context['schedule_rows']}
        self.assertEqual(states, {'HELD', 'PENDING'})

    def test_out_of_term_date_is_rejected(self):
        self.client.force_login(self.admin)
        outside = self.term.start_date - timedelta(days=1)
        response = self.client.get(reverse('admin_sessions'), {'date': outside.isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.context['selected_date'], outside)
        self.assertTrue(self.term.start_date <= response.context['selected_date'] <= self.term.end_date)


class DashboardMakeupCounterTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        month_start = self.today.replace(day=1)
        month_end = self.today.replace(day=monthrange(self.today.year, self.today.month)[1])
        start = month_start + timedelta(days=2)
        end = month_end - timedelta(days=2)
        if end < start:
            start, end = month_start, month_end
        self.term = AcademicTerm.objects.create(
            name='Makeup Counter Test Term', start_date=start, end_date=end, is_active=True,
        )
        programme = Programme.objects.create(code='MCT', name='Makeup Counter')
        group = ClassGroup.objects.create(
            code='MCT-A', programme=programme, term=self.term, semester_number=1,
        )
        teacher = User.objects.create_user(
            username='MCT-T', password='Example123!', role=User.Role.LECTURER,
        )
        subject = Subject.objects.create(code='MCT-1', name='Makeup Subject', short_name='Makeup')
        self.offering = ClassSubject.objects.create(
            class_group=group, subject=subject, lecturer=teacher,
        )
        self.offering.class_groups.add(group)
        self.admin = User.objects.create_superuser('mct-admin', password='Example123!')

        MakeupClass.objects.create(
            class_subject=self.offering, lecture_date=start, lecture_number=5,
            requested_by=self.admin, status=MakeupClass.APPROVED,
            reviewed_by=self.admin, reviewed_at=timezone.now(),
        )
        MakeupClass.objects.create(
            class_subject=self.offering, lecture_date=end, lecture_number=6,
            requested_by=self.admin, status=MakeupClass.APPROVED,
            reviewed_by=self.admin, reviewed_at=timezone.now(),
        )
        invalid_date = month_start if month_start < start else month_end
        if not (self.term.start_date <= invalid_date <= self.term.end_date):
            MakeupClass.objects.create(
                class_subject=self.offering, lecture_date=invalid_date, lecture_number=7,
                requested_by=self.admin, status=MakeupClass.APPROVED,
                reviewed_by=self.admin, reviewed_at=timezone.now(),
            )

    def test_month_counter_counts_full_month_but_only_inside_active_term(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['makeup_month'], 2)
