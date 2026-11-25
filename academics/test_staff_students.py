"""v2.8.10: staff profiles, permissions and one-time student password reset."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from attendance.models import AttendanceRecord, LectureSession
from fines.models import FineLedgerEntry, FinePolicy
from .models import AcademicTerm, ClassGroup, ClassMembership, ClassSubject, Programme, StudentProfile, Subject, WeeklySchedule


class StaffStudentProfilesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        today = timezone.localdate()
        cls.term = AcademicTerm.objects.create(name='Staff profile current term', start_date=today - timedelta(days=20), end_date=today + timedelta(days=30), is_active=True)
        cls.past_term = AcademicTerm.objects.create(name='Staff profile past term', start_date=today - timedelta(days=180), end_date=today - timedelta(days=21))
        cls.programme = Programme.objects.create(code='STAFFTEST', name='Test Programme')
        cls.group = ClassGroup.objects.create(code='STAFF-1', programme=cls.programme, term=cls.term, semester_number=1)
        cls.past_group = ClassGroup.objects.create(code='STAFF-OLD', programme=cls.programme, term=cls.past_term, semester_number=1)
        cls.admin = User.objects.create_user('staff-admin', password='AdminExample123!', role=User.Role.ADMIN)
        cls.superadmin = User.objects.create_superuser('staff-superadmin', password='AdminExample123!')
        cls.accounts = User.objects.create_user('staff-accounts', password='AdminExample123!', role=User.Role.ACCOUNTS)
        cls.teacher = User.objects.create_user('staff-teacher', first_name='Profile Lecturer', role=User.Role.LECTURER)
        cls.student_user = User.objects.create_user('ST-1001', first_name='Profile', last_name='Student', password='OldExample123!', role=User.Role.STUDENT)
        cls.student = StudentProfile.objects.create(user=cls.student_user, father_name='Example Father', whatsapp_number='+923001234567')
        cls.other_user = User.objects.create_user('ST-1002', first_name='Historical Learner', password='OtherExample123!', role=User.Role.STUDENT, is_active=False)
        cls.other = StudentProfile.objects.create(user=cls.other_user)
        ClassMembership.objects.create(student=cls.student, term=cls.term, class_group=cls.group)
        ClassMembership.objects.create(student=cls.student, term=cls.past_term, class_group=cls.past_group)
        ClassMembership.objects.create(student=cls.other, term=cls.past_term, class_group=cls.past_group)
        subject = Subject.objects.create(code='SP101', name='Profile Subject', short_name='PS')
        cls.offering = ClassSubject.objects.create(class_group=cls.group, subject=subject, lecturer=cls.teacher)
        cls.offering.class_groups.add(cls.group)
        cls.past_offering = ClassSubject.objects.create(class_group=cls.past_group, subject=subject, lecturer=cls.teacher)
        # Deliberately leave the legacy primary-only class link on this offering.
        legacy_subject = Subject.objects.create(code='SP102', name='Legacy Subject', short_name='LS')
        cls.legacy = ClassSubject.objects.create(class_group=cls.group, subject=legacy_subject, lecturer=cls.teacher)
        WeeklySchedule.objects.create(class_subject=cls.offering, weekday=0, lecture_number=1)
        WeeklySchedule.objects.create(class_subject=cls.legacy, weekday=1, lecture_number=2)
        for i, status in enumerate(('SUBMITTED', 'SUBMITTED', 'CANCELLED')):
            session = LectureSession.objects.create(class_subject=cls.offering, lecture_date=today - timedelta(days=i), lecture_number=1, status=status, submitted_by=cls.admin)
            AttendanceRecord.objects.create(session=session, student=cls.student, status=AttendanceRecord.PRESENT if i == 0 else AttendanceRecord.ABSENT)
        FineLedgerEntry.objects.create(student=cls.student, class_subject=cls.offering, kind='CHARGE', amount=Decimal('500.00'), actor=cls.admin)
        FineLedgerEntry.objects.create(student=cls.student, class_subject=cls.offering, kind='PAYMENT', amount=Decimal('-100.00'), actor=cls.admin)
        FineLedgerEntry.objects.create(student=cls.student, class_subject=cls.past_offering, kind='CHARGE', amount=Decimal('200.00'), actor=cls.admin)
        FineLedgerEntry.objects.create(student=cls.student, class_subject=cls.legacy, kind='PAYMENT', amount=Decimal('-50.00'), actor=cls.admin)

    def setUp(self):
        self.client.force_login(self.admin)
        self.search_url = reverse('student_profiles')
        self.detail_url = reverse('student_profile_detail', args=[self.student.pk])
        self.reset_url = reverse('student_reset_password', args=[self.student.pk])

    def confirm(self, url=None, client=None):
        return (client or self.client).get(url or self.reset_url).context['confirmation_token']

    def reset(self, url=None, client=None):
        c = client or self.client
        url = url or self.reset_url
        return c.post(url, {'confirm': 'yes', 'confirmation_token': self.confirm(url, c)})

    def test_staff_search_empty_until_submitted_and_four_search_fields(self):
        response = self.client.get(self.search_url)
        self.assertEqual(response.context['results'], [])
        self.assertNotContains(response, self.student.user.username)
        for query in ('ST-1001', 'profile student', 'Example Father', '0300-1234567', '+92 300 1234567', '00923001234567'):
            with self.subTest(query=query):
                response = self.client.post(self.search_url, {'q': query})
                self.assertEqual([s.pk for s in response.context['results']], [self.student.pk])
                self.assertContains(response, self.detail_url)
        response = self.client.post(self.search_url, {'q': 'ST-1002'})
        self.assertContains(response, 'Inactive')
        self.assertEqual([s.pk for s in response.context['results']], [self.other.pk])
        self.assertEqual(self.client.post(self.search_url, {'q': 'nonexistent'}).context['results'], [])

    def test_profile_current_scope_financial_semantics_and_history(self):
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['membership'].term_id, self.term.pk)
        self.assertEqual(response.context['summary']['total'], 2)
        self.assertEqual(response.context['summary']['present'], 1)
        self.assertEqual(response.context['summary']['percentage'], 50.0)
        self.assertEqual(response.context['summary']['outstanding'], Decimal('600.00'))
        self.assertEqual(response.context['summary']['subject_count'], 2)
        self.assertEqual(response.context['weekly']['summary']['lecture_count'], 2)
        self.assertEqual(len(response.context['memberships']), 2)
        self.assertContains(response, 'Profile Lecturer')
        self.assertContains(response, 'Legacy Subject')
        self.assertContains(response, self.past_term.name)
        self.assertNotContains(response, self.other_user.username)
        self.assertFalse(FinePolicy.objects.filter(term=self.term).exists())
        self.assertIn('no-store', response['Cache-Control'])

    def test_historical_inactive_profile_is_accessible(self):
        response = self.client.get(reverse('student_profile_detail', args=[self.other.pk]))
        self.assertContains(response, 'No active enrolment')
        self.assertContains(response, 'Inactive')
        self.assertContains(response, 'Contact details incomplete')
        self.assertContains(response, self.past_term.name)
        self.assertIsNone(response.context['summary']['percentage'])
        self.assertEqual(response.context['weekly']['summary']['lecture_count'], 0)

    def test_admin_and_accounts_navigation_permissions(self):
        for user in (self.admin, self.superadmin, self.accounts):
            with self.subTest(role=user.role, superuser=user.is_superuser):
                self.client.force_login(user)
                response = self.client.get(self.detail_url)
                self.assertContains(response, self.search_url)
                self.assertContains(response, reverse('student_edit', args=[self.student.pk]))
                self.assertContains(response, reverse('fine_student_detail', args=[self.student.pk]))
                self.assertContains(response, reverse('student_attendance'))
                roster = self.client.get(reverse('students_list'))
                self.assertContains(roster, self.detail_url)
                if user.role == User.Role.ACCOUNTS:
                    self.assertNotContains(response, self.reset_url)
                    self.assertNotContains(roster, self.reset_url)
                    self.assertNotContains(response, reverse('student_delete', args=[self.student.pk]))
                    self.assertEqual(self.client.get(self.reset_url).status_code, 403)
                    self.assertEqual(self.client.post(self.reset_url, {'confirm': 'yes'}).status_code, 403)
                else:
                    self.assertContains(response, self.reset_url)
                    self.assertContains(roster, self.reset_url)
                    self.assertEqual(self.client.get(self.reset_url).status_code, 200)

    def test_student_and_lecturer_denied_and_anonymous_redirected(self):
        for user in (self.student_user, self.teacher):
            self.client.force_login(user)
            for url in (self.search_url, self.detail_url, self.reset_url):
                self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(self.search_url, {'q': 'ST-1002'}).status_code, 403)
            self.assertEqual(self.client.post(self.reset_url, {'confirm': 'yes'}).status_code, 403)
        self.client.logout()
        for url in (self.search_url, self.detail_url, self.reset_url):
            self.assertRedirects(self.client.get(url), reverse('login') + '?next=' + url, fetch_redirect_response=False)

    def test_staff_edit_can_return_to_selected_profile(self):
        self.client.force_login(self.accounts)
        response = self.client.post(reverse('student_edit', args=[self.student.pk]), {
            'registration_number': self.student_user.username, 'student_name': 'Updated Student',
            'father_name': 'Updated Father', 'whatsapp_number': '03001234568', 'return_to': 'profile',
        })
        self.assertRedirects(response, self.detail_url, fetch_redirect_response=False)
        self.student.refresh_from_db()
        self.assertEqual(self.student.whatsapp_number, '+923001234568')
        self.assertEqual(self.student.father_name, 'Updated Father')

    def test_reset_get_and_unconfirmed_post_do_not_change_credentials(self):
        before = self.student_user.password
        response = self.client.get(self.reset_url)
        self.assertContains(response, 'Generate temporary password')
        self.assertNotContains(response, 'newStudentPassword')
        self.assertEqual(self.client.post(self.reset_url, {'confirmation_token': response.context['confirmation_token']}).status_code, 400)
        self.student_user.refresh_from_db()
        self.assertEqual(self.student_user.password, before)

    def test_admin_reset_password_once_without_data_loss(self):
        old_session = Client()
        self.assertTrue(old_session.login(username=self.student_user.username, password='OldExample123!'))
        other_hash = self.other_user.password
        token = self.confirm()
        response = self.client.post(self.reset_url, {'confirm': 'yes', 'confirmation_token': token, 'password': 'AttackerChosen!', 'student_id': self.other.pk})
        self.assertEqual(response.status_code, 200)
        temp = response.context['temporary_password']
        self.assertEqual(len(temp), 16)
        self.assertNotEqual(temp, 'AttackerChosen!')
        self.assertContains(response, 'copyTemporaryPassword')
        self.assertIn('no-store', response['Cache-Control'])
        self.student_user.refresh_from_db(); self.student.refresh_from_db(); self.other_user.refresh_from_db()
        self.assertTrue(self.student_user.check_password(temp))
        self.assertFalse(self.student_user.check_password('OldExample123!'))
        self.assertTrue(self.student_user.must_change_password)
        self.assertEqual(self.student.father_name, 'Example Father')
        self.assertEqual(self.student.whatsapp_number, '+923001234567')
        self.assertEqual(self.student.memberships.count(), 2)
        self.assertEqual(self.student.attendance_records.count(), 3)
        self.assertEqual(self.student.fine_entries.count(), 4)
        self.assertEqual(self.other_user.password, other_hash)
        self.assertNotIn(temp, str(dict(self.client.session)))
        self.assertNotContains(self.client.get(self.reset_url), temp)
        old_session_response = old_session.get(reverse('dashboard'))
        self.assertEqual(old_session_response.status_code, 302)
        self.assertTrue(old_session_response['Location'].startswith(reverse('login')))
        self.assertEqual(self.client.post(self.reset_url, {'confirm': 'yes', 'confirmation_token': token}).status_code, 409)
        self.student_user.refresh_from_db()
        self.assertTrue(self.student_user.check_password(temp))

    def test_reset_then_password_change_and_contact_gate_in_correct_order(self):
        self.student.father_name = ''
        self.student.save(update_fields=['father_name'])
        response = self.reset()
        temp = response.context['temporary_password']
        c = Client()
        self.assertTrue(c.login(username=self.student_user.username, password=temp))
        self.assertRedirects(c.get(reverse('student_my_attendance')), reverse('password_change'), fetch_redirect_response=False)
        self.assertRedirects(c.post(reverse('password_change'), {'old_password': temp, 'new_password1': 'ChangedProfile987!q', 'new_password2': 'ChangedProfile987!q'}), reverse('dashboard'), fetch_redirect_response=False)
        self.assertRedirects(c.get(reverse('dashboard')), reverse('student_complete_profile'), fetch_redirect_response=False)
        self.assertRedirects(c.post(reverse('student_complete_profile'), {'father_name': 'Completed Father'}), reverse('dashboard'), fetch_redirect_response=False)
        self.assertEqual(c.get(reverse('dashboard')).status_code, 200)
        self.student_user.refresh_from_db()
        self.assertFalse(self.student_user.must_change_password)
        self.assertFalse(self.student_user.check_password(temp))

    def test_reset_token_bound_to_actor_target_and_current_password(self):
        token = self.confirm()
        self.client.force_login(self.superadmin)
        self.assertEqual(self.client.post(self.reset_url, {'confirm': 'yes', 'confirmation_token': token}).status_code, 409)
        self.client.force_login(self.admin)
        other_url = reverse('student_reset_password', args=[self.other.pk])
        self.assertEqual(self.client.post(other_url, {'confirm': 'yes', 'confirmation_token': token}).status_code, 409)
        self.assertEqual(self.client.post(self.reset_url, {'confirm': 'yes', 'confirmation_token': 'forged'}).status_code, 409)
        self.student_user.set_password('NewIndependent987!'); self.student_user.save(update_fields=['password'])
        self.assertEqual(self.client.post(self.reset_url, {'confirm': 'yes', 'confirmation_token': token}).status_code, 409)
        self.student_user.refresh_from_db()
        self.assertTrue(self.student_user.check_password('NewIndependent987!'))

    def test_reset_inactive_account_does_not_activate(self):
        self.client.force_login(self.superadmin)
        response = self.reset(reverse('student_reset_password', args=[self.other.pk]))
        self.assertEqual(response.status_code, 200)
        self.other_user.refresh_from_db()
        self.assertFalse(self.other_user.is_active)
        self.assertTrue(self.other_user.must_change_password)
        self.assertTrue(self.other_user.check_password(response.context['temporary_password']))

    def test_privileged_non_student_profile_cannot_be_reset(self):
        bogus = StudentProfile.objects.create(user=self.superadmin)
        before = self.superadmin.password
        url = reverse('student_reset_password', args=[bogus.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {'confirm': 'yes', 'confirmation_token': self.confirm()}).status_code, 404)
        self.assertEqual(self.client.get(reverse('student_profile_detail', args=[bogus.pk])).status_code, 404)
        self.superadmin.refresh_from_db()
        self.assertEqual(self.superadmin.password, before)

    def test_csrf_required_for_reset_and_search(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.admin)
        token = self.confirm(client=c)
        self.assertEqual(c.post(self.reset_url, {'confirm': 'yes', 'confirmation_token': token}).status_code, 403)
        self.assertEqual(c.post(self.search_url, {'q': 'ST-1001'}).status_code, 403)
        self.student_user.refresh_from_db()
        self.assertTrue(self.student_user.check_password('OldExample123!'))

    def test_confirmation_expires(self):
        # TimestampSigner embeds its clock value when the form is generated.
        import time
        with patch('django.core.signing.time.time', return_value=time.time() - 601):
            token = self.confirm()
        self.assertEqual(self.client.post(self.reset_url, {'confirm': 'yes', 'confirmation_token': token}).status_code, 409)
        self.student_user.refresh_from_db()
        self.assertTrue(self.student_user.check_password('OldExample123!'))
