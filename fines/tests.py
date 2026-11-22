from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from academics.models import (
    AcademicTerm, AppBranding, ClassGroup, ClassMembership,
    ClassSubject, Programme, StudentProfile, Subject,
)
from attendance.models import AttendanceRecord, LectureSession

from .models import FineLedgerEntry, FinePolicy


class FineChallanV285Tests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.term = AcademicTerm.objects.create(
            name='Fine Challan Test',
            start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=120),
            is_active=True,
        )
        self.programme = Programme.objects.create(code='CHL', name='Challan Programme')
        self.group = ClassGroup.objects.create(
            code='CHL-1', programme=self.programme, term=self.term, semester_number=1,
        )
        self.admin = User.objects.create_superuser('challanadmin', password='Example123!')
        self.lecturer = User.objects.create_user(
            'CHL-T01', password='Example123!', role=User.Role.LECTURER,
            first_name='Test', last_name='Teacher',
        )
        user = User.objects.create_user(
            'CHL-S01', password='Example123!', role=User.Role.STUDENT,
            first_name='Ayesha', last_name='Khan',
        )
        self.student = StudentProfile.objects.create(user=user)
        ClassMembership.objects.create(student=self.student, term=self.term, class_group=self.group)
        subject = Subject.objects.create(code='CHL-101', name='Data Structures', short_name='DS')
        self.offering = ClassSubject.objects.create(
            class_group=self.group, subject=subject, lecturer=self.lecturer,
        )
        self.offering.class_groups.add(self.group)
        FinePolicy.objects.create(
            term=self.term, allowed_absences=1, rate_per_extra_absence=Decimal('100.00'),
        )
        for index in range(3):
            session = LectureSession.objects.create(
                class_subject=self.offering,
                lecture_date=today - timedelta(days=index + 1),
                lecture_number=index + 1,
                status='SUBMITTED',
                submitted_by=self.admin,
            )
            AttendanceRecord.objects.create(
                session=session, student=self.student, status=AttendanceRecord.ABSENT,
            )
        FineLedgerEntry.objects.create(
            student=self.student, class_subject=self.offering, kind='CHARGE',
            amount=Decimal('200.00'), note='Test charge', actor=self.admin,
        )

    def test_challan_is_admin_only_and_uses_configurable_institute_name(self):
        branding = AppBranding.objects.get(pk=1)
        branding.institute_name = 'Clasvanta Academy'
        branding.save()

        self.client.force_login(self.admin)
        response = self.client.get(reverse('fine_challan', args=[self.student.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Clasvanta Academy')
        self.assertContains(response, 'Ayesha Khan')
        self.assertContains(response, 'CHL-S01')
        self.assertContains(response, 'PKR 200.00')
        self.assertEqual(response.context['total_absences'], 3)
        self.assertEqual(response.context['total_fineable'], 2)
        self.assertEqual(response.context['total_payable'], Decimal('200.00'))

        self.client.force_login(self.lecturer)
        self.assertEqual(
            self.client.get(reverse('fine_challan', args=[self.student.pk])).status_code,
            403,
        )

    def test_fines_screen_has_print_challan_action(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('fines_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Print challan')
        self.assertContains(response, reverse('fine_challan', args=[self.student.pk]))
