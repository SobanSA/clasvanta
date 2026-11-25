"""v2.8.9 regression coverage for compulsory student contact completion."""
from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from .models import AcademicTerm, ClassGroup, ClassMembership, Programme, StudentProfile


class CompulsoryStudentContactTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        today = timezone.localdate()
        cls.term = AcademicTerm.objects.create(name='Contacts Test Term', start_date=today - timedelta(days=7), end_date=today + timedelta(days=30), is_active=True)
        cls.programme = Programme.objects.create(code='CONTACT', name='Contact Test Programme')
        cls.group = ClassGroup.objects.create(code='CONTACT-A', name='Semester 1', programme=cls.programme, term=cls.term, semester_number=1)
        cls.admin = User.objects.create_superuser('contact-admin', password='Example123!')
        cls.regular_admin = User.objects.create_user('contact-regular-admin', password='Example123!', role=User.Role.ADMIN)
        cls.accounts = User.objects.create_user('contact-accounts', password='Example123!', role=User.Role.ACCOUNTS)
        cls.lecturer = User.objects.create_user('contact-lecturer', password='Example123!', role=User.Role.LECTURER)
        cls.student_user = User.objects.create_user('CONTACT-001', password='Example123!', first_name='Original Student', role=User.Role.STUDENT)
        cls.student = StudentProfile.objects.create(user=cls.student_user)
        cls.other_user = User.objects.create_user('CONTACT-002', password='Example123!', first_name='Other Student', role=User.Role.STUDENT)
        cls.other_student = StudentProfile.objects.create(user=cls.other_user, father_name='Other Father', whatsapp_number='+923001234568')
        for profile in (cls.student, cls.other_student):
            ClassMembership.objects.create(student=profile, term=cls.term, class_group=cls.group)

    def setUp(self):
        self.client.force_login(self.student_user)
        self.complete_url = reverse('student_complete_profile')
        self.update_url = reverse('student_update_whatsapp')

    def set_details(self, father='', number=''):
        StudentProfile.objects.filter(pk=self.student.pk).update(father_name=father, whatsapp_number=number)
        self.student.refresh_from_db()

    def submit_complete(self, **data):
        return self.client.post(self.complete_url, data)

    def test_direct_portal_urls_are_blocked_until_complete(self):
        for name in ('dashboard', 'student_my_attendance', 'student_schedule', 'student_fines', 'student_profile', 'student_update_whatsapp'):
            with self.subTest(route=name):
                self.assertRedirects(self.client.get(reverse(name)), self.complete_url, fetch_redirect_response=False)
        self.assertRedirects(self.client.post(self.update_url, {'whatsapp_number': '03001234567'}), self.complete_url, fetch_redirect_response=False)
        # Fresh login with a direct next URL still goes through the gate.
        self.client.logout()
        response = self.client.post(reverse('login'), {'username': self.student_user.username, 'password': 'Example123!', 'next': reverse('student_fines')}, follow=True)
        self.assertEqual(response.request['PATH_INFO'], self.complete_url)
        self.assertContains(response, 'Complete your profile')

    def test_two_missing_fields_are_required_and_saved_together(self):
        response = self.client.get(self.complete_url)
        self.assertContains(response, 'name="father_name"')
        self.assertContains(response, 'name="whatsapp_number"')
        self.assertNotContains(response, 'Remind me later')
        self.assertContains(response, 'Sign out')
        response = self.submit_complete(father_name='Test Father')
        self.assertEqual(response.status_code, 200)
        self.assertIn('whatsapp_number', response.context['form'].errors)
        self.student.refresh_from_db()
        self.assertEqual(self.student.father_name, '')
        response = self.submit_complete(father_name='  Test Father  ', whatsapp_number='0300-1234567', student_name='Tampered', registration_number='CHANGED', student=self.other_student.pk)
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.student.refresh_from_db(); self.student_user.refresh_from_db(); self.other_student.refresh_from_db()
        self.assertEqual(self.student.father_name, 'Test Father')
        self.assertEqual(self.student.whatsapp_number, '+923001234567')
        self.assertEqual(self.student_user.username, 'CONTACT-001')
        self.assertEqual(self.student_user.first_name, 'Original Student')
        self.assertEqual(self.other_student.father_name, 'Other Father')
        self.assertTrue(self.student.contact_details_complete)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

    def test_existing_father_name_cannot_be_overwritten(self):
        self.set_details(father='Admin Father')
        response = self.client.get(self.complete_url)
        self.assertNotContains(response, 'name="father_name"')
        self.assertContains(response, 'name="whatsapp_number"')
        # Simulate a stale/malicious submission after admin has populated the name.
        response = self.submit_complete(father_name='Wrong Father', whatsapp_number='03001234567')
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.student.refresh_from_db()
        self.assertEqual(self.student.father_name, 'Admin Father')
        self.assertEqual(self.student.whatsapp_number, '+923001234567')

    def test_existing_whatsapp_not_requested_or_overwritten_at_completion(self):
        self.set_details(number='+923001234567')
        response = self.client.get(self.complete_url)
        self.assertContains(response, 'name="father_name"')
        self.assertNotContains(response, 'name="whatsapp_number"')
        response = self.submit_complete(father_name='New Father', whatsapp_number='03001234568')
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.student.refresh_from_db()
        self.assertEqual(self.student.whatsapp_number, '+923001234567')
        self.assertEqual(self.student.father_name, 'New Father')

    def test_complete_student_never_sees_completion_form(self):
        self.set_details('Saved Father', '+923001234567')
        self.assertRedirects(self.client.get(self.complete_url), reverse('dashboard'), fetch_redirect_response=False)
        self.assertRedirects(self.submit_complete(father_name='Tampered', whatsapp_number='03001234568'), reverse('dashboard'), fetch_redirect_response=False)
        self.student.refresh_from_db()
        self.assertEqual(self.student.father_name, 'Saved Father')
        self.assertEqual(self.student.whatsapp_number, '+923001234567')
        for name in ('dashboard', 'student_my_attendance', 'student_schedule', 'student_fines', 'student_profile'):
            with self.subTest(route=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'Complete your profile')

    def test_blank_and_invalid_fields_do_not_unlock_portal(self):
        for father, number, field in [('   ', '03001234567', 'father_name'), ('Test Father', '', 'whatsapp_number'), ('Test Father', '12345', 'whatsapp_number'), ('X'*161, '03001234567', 'father_name')]:
            with self.subTest(field=field, number=number):
                response = self.submit_complete(father_name=father, whatsapp_number=number)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context['form'].errors)
                self.student.refresh_from_db()
                self.assertFalse(self.student.contact_details_complete)
        self.assertRedirects(self.client.get(reverse('dashboard')), self.complete_url, fetch_redirect_response=False)

    def test_password_change_is_first(self):
        User.objects.filter(pk=self.student_user.pk).update(must_change_password=True)
        for name in ('dashboard', 'student_my_attendance', 'student_complete_profile', 'student_update_whatsapp'):
            self.assertRedirects(self.client.get(reverse(name)), reverse('password_change'), fetch_redirect_response=False)
        self.assertRedirects(self.submit_complete(father_name='Father', whatsapp_number='03001234567'), reverse('password_change'), fetch_redirect_response=False)
        response = self.client.post(reverse('password_change'), {'old_password': 'Example123!', 'new_password1': 'R7!New-Pass-294', 'new_password2': 'R7!New-Pass-294'}, follow=True)
        self.assertEqual(response.request['PATH_INFO'], self.complete_url)
        self.assertContains(response, 'Complete your profile')
        self.student_user.refresh_from_db()
        self.assertFalse(self.student_user.must_change_password)

    def test_whatsapp_update_only_changes_own_number(self):
        self.set_details('Saved Father', '+923001234567')
        response = self.client.get(reverse('student_profile'))
        self.assertContains(response, 'Saved Father')
        self.assertContains(response, '+923001234567')
        self.assertContains(response, 'My weekly lectures')
        self.assertNotContains(response, 'name="father_name"')
        self.assertEqual(self.client.get(self.update_url).status_code, 405)
        response = self.client.post(self.update_url, {'whatsapp_number': '+44 7700 900123', 'father_name': 'Tampered', 'registration_number': 'CHANGED', 'student_name': 'Changed', 'student_id': self.other_student.pk})
        self.assertRedirects(response, reverse('student_profile'), fetch_redirect_response=False)
        self.student.refresh_from_db(); self.student_user.refresh_from_db(); self.other_student.refresh_from_db()
        self.assertEqual(self.student.whatsapp_number, '+447700900123')
        self.assertEqual(self.student.father_name, 'Saved Father')
        self.assertEqual(self.student_user.username, 'CONTACT-001')
        self.assertEqual(self.student_user.first_name, 'Original Student')
        self.assertEqual(self.other_student.whatsapp_number, '+923001234568')
        for number in ('', '123', '   '):
            response = self.client.post(self.update_url, {'whatsapp_number': number})
            self.assertEqual(response.status_code, 200)
            self.assertIn('whatsapp_number', response.context['whatsapp_form'].errors)
            self.student.refresh_from_db()
            self.assertEqual(self.student.whatsapp_number, '+447700900123')

    def test_shared_family_whatsapp_is_allowed(self):
        response = self.submit_complete(father_name='Family Father', whatsapp_number=self.other_student.whatsapp_number)
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.student.refresh_from_db()
        self.assertEqual(self.student.whatsapp_number, self.other_student.whatsapp_number)

    def test_staff_can_manage_contacts_but_students_cannot_use_staff_routes(self):
        edit_url = reverse('student_edit', args=[self.student.pk])
        self.assertEqual(self.client.get(edit_url).status_code, 403)
        self.assertEqual(self.client.post(edit_url, {'registration_number': 'CONTACT-001', 'student_name': 'Changed', 'father_name': 'Changed', 'whatsapp_number': '03001234567'}).status_code, 403)
        for staff in (self.admin, self.regular_admin, self.accounts):
            self.client.force_login(staff)
            data = {'registration_number': 'CONTACT-001', 'student_name': 'Original Student', 'father_name': 'Staff Father', 'whatsapp_number': '03001234567'}
            self.assertRedirects(self.client.post(edit_url, data), reverse('students_list'), fetch_redirect_response=False)
            self.student.refresh_from_db()
            self.assertEqual(self.student.father_name, 'Staff Father')
            self.assertEqual(self.student.whatsapp_number, '+923001234567')
            self.assertContains(self.client.get(reverse('students_list')), '+923001234567')
            self.assertEqual(self.client.get(self.complete_url).status_code, 403)
            self.assertEqual(self.client.post(self.update_url, {'whatsapp_number': '03001234568'}).status_code, 403)
        self.client.force_login(self.lecturer)
        self.assertEqual(self.client.get(self.complete_url).status_code, 403)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

    def test_roster_filters_and_admin_clear_reopens_gate(self):
        self.set_details('Saved Father', '+923001234567')
        self.client.force_login(self.admin)
        response = self.client.get(reverse('students_list'), {'contact': 'complete'})
        self.assertEqual(response.context['student_count'], 2)
        self.assertContains(response, '03001234567')  # Local-format search alias.
        edit_url = reverse('student_edit', args=[self.student.pk])
        self.assertRedirects(self.client.post(edit_url, {'registration_number': self.student_user.username, 'student_name': self.student_user.first_name, 'father_name': 'Saved Father', 'whatsapp_number': ''}), reverse('students_list'), fetch_redirect_response=False)
        response = self.client.get(reverse('students_list'), {'contact': 'incomplete'})
        self.assertEqual(response.context['student_count'], 1)
        self.assertEqual(response.context['rows'][0]['membership'].student_id, self.student.pk)
        self.client.force_login(self.student_user)
        self.assertRedirects(self.client.get(reverse('student_profile')), self.complete_url, fetch_redirect_response=False)
        response = self.client.get(self.complete_url)
        self.assertContains(response, 'name="whatsapp_number"')
        self.assertNotContains(response, 'name="father_name"')

    def test_admin_can_create_with_contacts_or_leave_missing(self):
        self.client.force_login(self.admin)
        for i, father, number in [(1, 'Admin Father', '03001234567'), (2, '', '')]:
            registration = f'CONTACT-NEW-{i}'
            response = self.client.post(reverse('student_add'), {'registration_number': registration, 'student_name': f'New Student {i}', 'father_name': father, 'whatsapp_number': number, 'class_group': self.group.pk})
            self.assertRedirects(response, reverse('student_add'), fetch_redirect_response=False)
            account = User.objects.get(username=registration)
            self.assertTrue(account.must_change_password)
            self.assertEqual(account.student_profile.contact_details_complete, i == 1)
        self.assertEqual(User.objects.filter(username__startswith='CONTACT-NEW-').count(), 2)

    def test_invalid_staff_edit_rolls_back_other_changes_and_old_clients_preserve_contacts(self):
        self.set_details('Saved Father', '+923001234567')
        self.client.force_login(self.admin)
        edit_url = reverse('student_edit', args=[self.student.pk])
        response = self.client.post(edit_url, {'registration_number': 'BAD-CHANGE', 'student_name': 'Bad Change', 'father_name': 'Wrong Father', 'whatsapp_number': '123'})
        self.assertEqual(response.status_code, 200)
        self.student.refresh_from_db(); self.student_user.refresh_from_db()
        self.assertEqual(self.student_user.username, 'CONTACT-001')
        self.assertEqual(self.student.father_name, 'Saved Father')
        self.assertEqual(self.student.whatsapp_number, '+923001234567')
        response = self.client.post(edit_url, {'registration_number': 'CONTACT-001', 'student_name': 'Original Student'})
        self.assertRedirects(response, reverse('students_list'), fetch_redirect_response=False)
        self.student.refresh_from_db()
        self.assertEqual(self.student.father_name, 'Saved Father')
        self.assertEqual(self.student.whatsapp_number, '+923001234567')

    def test_whitespace_legacy_father_is_missing_and_no_enrollment_is_required(self):
        self.set_details('   ', '+923001234567')
        ClassMembership.objects.filter(student=self.student).delete()
        self.assertRedirects(self.client.get(reverse('dashboard')), self.complete_url, fetch_redirect_response=False)
        self.assertRedirects(self.submit_complete(father_name='New Father'), reverse('dashboard'), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse('dashboard')), 'No active class enrollment')

    def test_csrf_and_logout_are_preserved(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.student_user)
        response = csrf_client.post(self.complete_url, {'father_name': 'Father', 'whatsapp_number': '03001234567'})
        self.assertEqual(response.status_code, 403)
        response = self.client.get(self.complete_url)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.client.post(reverse('logout'))
        response = self.client.get(self.complete_url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith(reverse('login')))
