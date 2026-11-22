from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from attendance.models import AttendanceRecord, LectureSession, MakeupClass, SessionDeletionAudit
from attendance.services import delete_held_session
from fines.models import FineLedgerEntry, FinePolicy
from .models import (
    AcademicTerm, ClassGroup, ClassMembership, ClassSubject,
    Programme, StudentProfile, Subject, WeeklySchedule,
)


class ReportsV28Tests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        # Start the term today so every recurring schedule contributes exactly
        # one occurrence regardless of which day of the month the test is run.
        self.term = AcademicTerm.objects.create(
            name='Reports Test Term',
            start_date=self.today,
            end_date=self.today + timedelta(days=365),
            is_active=True,
        )
        self.programme = Programme.objects.create(code='RPT', name='Reporting Programme')
        self.class_a = ClassGroup.objects.create(
            code='RPT-A', programme=self.programme, term=self.term, semester_number=1,
        )
        self.class_b = ClassGroup.objects.create(
            code='RPT-B', programme=self.programme, term=self.term, semester_number=1,
        )
        self.admin = User.objects.create_superuser('reportadmin', password='Example123!')
        self.teacher = User.objects.create_user(
            'RPT-T01', password='Example123!', role=User.Role.LECTURER,
            first_name='Report', last_name='Teacher',
        )
        self.students = []
        for username, name, group in (
            ('RPT-S01', 'Student One', self.class_a),
            ('RPT-S02', 'Student Two', self.class_b),
        ):
            user = User.objects.create_user(
                username, password='Example123!', role=User.Role.STUDENT, first_name=name,
            )
            profile = StudentProfile.objects.create(user=user)
            ClassMembership.objects.create(student=profile, term=self.term, class_group=group)
            self.students.append(profile)

        self.subject = Subject.objects.create(code='RPT-101', name='Reporting Systems', short_name='Reports')
        self.section = ClassSubject.objects.create(
            class_group=self.class_a, subject=self.subject, lecturer=self.teacher,
        )
        self.section.class_groups.add(self.class_a, self.class_b)
        for lecture_number in (1, 2, 3):
            WeeklySchedule.objects.create(
                class_subject=self.section,
                weekday=self.today.weekday(),
                lecture_number=lecture_number,
            )

        self.held = LectureSession.objects.create(
            class_subject=self.section, lecture_date=self.today, lecture_number=1,
            status='SUBMITTED', submitted_by=self.admin,
        )
        AttendanceRecord.objects.create(session=self.held, student=self.students[0], status='A')
        AttendanceRecord.objects.create(session=self.held, student=self.students[1], status='P')

        self.cancelled = LectureSession.objects.create(
            class_subject=self.section, lecture_date=self.today, lecture_number=2,
            status='CANCELLED', submitted_by=self.admin, cancellation_reason='Reports test',
        )
        # Lecture 3 deliberately has no session => Not Marked/Pending.

        self.makeup = MakeupClass.objects.create(
            class_subject=self.section, lecture_date=self.today, lecture_number=4,
            requested_by=self.admin, status=MakeupClass.APPROVED,
            reviewed_by=self.admin, reviewed_at=timezone.now(),
        )
        self.makeup_session = LectureSession.objects.create(
            class_subject=self.section, lecture_date=self.today, lecture_number=4,
            status='SUBMITTED', submitted_by=self.admin,
        )
        AttendanceRecord.objects.create(session=self.makeup_session, student=self.students[0], status='P')
        AttendanceRecord.objects.create(session=self.makeup_session, student=self.students[1], status='P')

        FinePolicy.objects.create(
            term=self.term, allowed_absences=0, rate_per_extra_absence=Decimal('100.00'),
        )
        FineLedgerEntry.objects.create(
            student=self.students[0], class_subject=self.section, kind='CHARGE',
            amount=Decimal('100.00'), note='Reports test charge', actor=self.admin,
        )

    def _month(self):
        return self.today.strftime('%Y-%m')

    def test_reports_are_admin_only(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('reports')).status_code, 200)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse('reports')).status_code, 403)
        self.client.force_login(self.students[0].user)
        self.assertEqual(self.client.get(reverse('reports')).status_code, 403)

    def test_compliance_preserves_held_cancelled_pending_makeup_and_merged_rules(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('reports'), {
            'report': 'compliance', 'month': self._month(), 'subject': self.subject.pk,
        })
        self.assertEqual(response.status_code, 200)
        summary = response.context['data']['summary']
        self.assertEqual(summary['scheduled'], 4)
        self.assertEqual(summary['held'], 2)
        self.assertEqual(summary['cancelled'], 1)
        self.assertEqual(summary['pending'], 1)
        self.assertEqual(summary['makeup'], 1)
        self.assertEqual(summary['completion'], 50.0)

        # The shared section appears in both class reports, but is one lecturer occurrence.
        class_rows = response.context['data']['class_rows']
        self.assertEqual(len(class_rows), 2)
        self.assertTrue(all(row['scheduled'] == 4 for row in class_rows))
        teacher_rows = response.context['data']['teacher_rows']
        self.assertEqual(len(teacher_rows), 1)
        self.assertEqual(teacher_rows[0]['scheduled'], 4)

    def test_class_report_filters_merged_attendance_to_selected_class_students(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('reports'), {
            'report': 'class', 'month': self._month(), 'class': self.class_a.pk,
        })
        self.assertEqual(response.status_code, 200)
        data = response.context['data']
        self.assertEqual(data['selected_class'], self.class_a)
        self.assertEqual(len(data['student_rows']), 1)
        student_row = data['student_rows'][0]
        self.assertEqual(student_row['student'], self.students[0])
        self.assertEqual(student_row['present'], 1)
        self.assertEqual(student_row['absent'], 1)
        self.assertEqual(student_row['attendance_rate'], 50.0)
        subject_row = data['subject_rows'][0]
        self.assertEqual(subject_row['held'], 2)
        self.assertEqual(subject_row['cancelled'], 1)
        self.assertEqual(subject_row['pending'], 1)

    def test_defaulters_use_existing_term_absence_policy(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('reports'), {
            'report': 'defaulters', 'month': self._month(), 'subject': self.subject.pk,
        })
        self.assertEqual(response.status_code, 200)
        rows = response.context['data']['rows']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['student_id'], self.students[0].pk)
        self.assertEqual(rows[0]['allowed'], 0)
        self.assertEqual(rows[0]['term_absent'], 1)
        self.assertEqual(rows[0]['excess'], 1)
        self.assertEqual(rows[0]['fine_balance'], Decimal('100.00'))

    def test_daily_and_student_history_use_submitted_records_only(self):
        self.client.force_login(self.admin)
        daily = self.client.get(reverse('reports'), {
            'report': 'daily', 'date': self.today.isoformat(), 'month': self._month(),
        })
        self.assertEqual(daily.status_code, 200)
        self.assertEqual(daily.context['data']['summary']['held_all'], 2)
        self.assertEqual(daily.context['data']['summary']['cancelled'], 1)
        self.assertEqual(daily.context['data']['summary']['pending'], 1)

        history = self.client.get(reverse('reports'), {
            'report': 'student', 'month': self._month(), 'student': self.students[0].pk,
        })
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.context['data']['summary']['held'], 2)
        self.assertEqual(history.context['data']['summary']['present'], 1)
        self.assertEqual(history.context['data']['summary']['absent'], 1)
        self.assertEqual(len(history.context['data']['history']), 2)

    def test_class_filter_limits_merged_section_student_counts_and_balances(self):
        # Make the Class-B student absent/fined too. A Class-A report must still
        # remain scoped to Class-A students even though the teaching section is merged.
        record = AttendanceRecord.objects.get(session=self.held, student=self.students[1])
        record.status = 'A'
        record.save(update_fields=['status'])
        FineLedgerEntry.objects.create(
            student=self.students[1], class_subject=self.section, kind='CHARGE',
            amount=Decimal('100.00'), note='Class-B test charge', actor=self.admin,
        )

        self.client.force_login(self.admin)
        daily = self.client.get(reverse('reports'), {
            'report': 'daily', 'date': self.today.isoformat(), 'month': self._month(),
            'class': self.class_a.pk,
        })
        held_row = next(row for row in daily.context['data']['rows'] if row['lecture_number'] == 1)
        self.assertEqual(held_row['present'], 0)
        self.assertEqual(held_row['absent'], 1)

        defaulters = self.client.get(reverse('reports'), {
            'report': 'defaulters', 'month': self._month(), 'class': self.class_a.pk,
        })
        self.assertEqual(len(defaulters.context['data']['rows']), 1)
        self.assertEqual(defaulters.context['data']['rows'][0]['student_id'], self.students[0].pk)

        fines = self.client.get(reverse('reports'), {
            'report': 'fines', 'month': self._month(), 'class': self.class_a.pk,
        })
        self.assertEqual(fines.context['data']['summary']['outstanding_total'], Decimal('100.00'))
        self.assertEqual(len(fines.context['data']['balances']), 1)

    def test_deleted_held_session_returns_to_pending_in_reports(self):
        original_id = self.held.pk
        delete_held_session(
            actor=self.admin, session_id=original_id, reason='Wrong lecture was marked held',
        )
        self.assertFalse(LectureSession.objects.filter(pk=original_id).exists())
        self.assertTrue(SessionDeletionAudit.objects.filter(original_session_id=original_id).exists())

        self.client.force_login(self.admin)
        response = self.client.get(reverse('reports'), {
            'report': 'compliance', 'month': self._month(), 'subject': self.subject.pk,
        })
        summary = response.context['data']['summary']
        self.assertEqual(summary['scheduled'], 4)
        self.assertEqual(summary['held'], 1)
        self.assertEqual(summary['cancelled'], 1)
        self.assertEqual(summary['pending'], 2)
        self.assertEqual(summary['makeup'], 1)
        self.assertEqual(summary['completion'], 25.0)

        # The fine report consumes the reconciled append-only ledger. The
        # deleted absence is no longer an outstanding fine.
        fines = self.client.get(reverse('reports'), {
            'report': 'fines', 'month': self._month(), 'subject': self.subject.pk,
        })
        self.assertEqual(fines.context['data']['summary']['outstanding_total'], Decimal('0.00'))


    def test_monthly_lecturer_report_matches_sheet_style_and_omits_duration_column(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('reports'), {
            'report': 'monthly_lecturer', 'month': self._month(), 'class': self.class_a.pk,
        })
        self.assertEqual(response.status_code, 200)
        rows = response.context['data']['rows']
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row['lecturer'] == self.teacher for row in rows))
        self.assertTrue(all(row['class_group'] == self.class_a for row in rows))
        self.assertTrue(all(row['lec_in_timetable'] == 3 for row in rows))
        self.assertEqual(
            {row['status'] for row in rows},
            {'Held Lecture', 'Missing Lecture', 'Make-up Lecture'},
        )
        self.assertEqual(response.context['data']['summary']['held'], 1)
        self.assertEqual(response.context['data']['summary']['missing'], 1)
        self.assertEqual(response.context['data']['summary']['makeup'], 1)
        self.assertTrue(all(row['remarks'] == '' for row in rows))

        export = self.client.get(reverse('reports'), {
            'report': 'monthly_lecturer', 'month': self._month(), 'class': self.class_a.pk,
            'export': 'xlsx',
        })
        self.assertEqual(export.status_code, 200)
        self.assertEqual(
            export['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        self.assertTrue(export.content.startswith(b'PK'))

    def test_fine_report_and_excel_export(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('reports'), {
            'report': 'fines', 'month': self._month(),
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['data']['summary']['charges'], Decimal('100.00'))
        self.assertEqual(response.context['data']['summary']['outstanding_total'], Decimal('100.00'))

        export = self.client.get(reverse('reports'), {
            'report': 'compliance', 'month': self._month(), 'export': 'xlsx',
        })
        self.assertEqual(export.status_code, 200)
        self.assertEqual(
            export['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        self.assertTrue(export.content.startswith(b'PK'))

    def test_timetable_compliance_excludes_cancelled_and_uses_held_makeup(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('reports'), {
            'report': 'timetable_compliance',
            'month': self._month(),
            'class': self.class_a.pk,
        })
        self.assertEqual(response.status_code, 200)
        rows = response.context['data']['rows']
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['lecturer'], self.teacher)
        self.assertEqual(row['class_group'], self.class_a)
        self.assertEqual(row['lec_in_timetable'], 3)
        # Lecture 2 is Cancelled and deliberately excluded from this report.
        self.assertEqual(row['expected'], 2)
        self.assertEqual(row['held'], 1)
        self.assertEqual(row['missing'], 1)
        self.assertEqual(row['makeup_held'], 1)
        self.assertEqual(row['delivered'], 2)
        self.assertEqual(row['compliance'], 100.0)
        self.assertContains(response, 'How to read compliance')
