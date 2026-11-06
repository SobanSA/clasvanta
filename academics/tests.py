"""Admin lecturer directory and account security regression tests."""
from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from .models import AcademicTerm, ClassGroup, ClassSubject, Programme, Subject


class LecturerManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='admin-test', password='TestAdmin123!')
        self.client.force_login(self.admin)
        self.url = reverse('lecturers_manage')

    def test_create_teacher_shows_password_once_and_force_change(self):
        response = self.client.post(self.url, {
            'action': 'create', 'teacher_id': 'T-901', 'name': 'Anum Shah',
        })
        self.assertEqual(response.status_code, 302)
        teacher = User.objects.get(username='T-901')
        self.assertEqual(teacher.role, 'LECTURER')
        self.assertFalse(teacher.is_staff)
        self.assertTrue(teacher.is_active)
        self.assertTrue(teacher.must_change_password)
        first_view = self.client.get(self.url)
        password = first_view.context['credentials']['password']
        self.assertTrue(teacher.check_password(password))
        self.assertIsNone(self.client.get(self.url).context['credentials'])

        self.client.post(self.url, {'action': 'reset_password', 'lecturer_id': str(teacher.pk)})
        reset_view = self.client.get(self.url)
        reset_password = reset_view.context['credentials']['password']
        teacher.refresh_from_db()
        self.assertTrue(teacher.check_password(reset_password))
        self.assertFalse(teacher.check_password(password))
        self.assertTrue(teacher.must_change_password)

        self.client.post(self.url, {
            'action': 'set_active', 'lecturer_id': str(teacher.pk), 'is_active': '0',
        })
        teacher.refresh_from_db()
        self.assertFalse(teacher.is_active)

    def test_students_cannot_manage_lecturers_and_admin_cannot_be_reset_here(self):
        old_hash = self.admin.password
        response = self.client.post(self.url, {
            'action': 'reset_password', 'lecturer_id': str(self.admin.pk),
        })
        self.assertEqual(response.status_code, 404)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.password, old_hash)
        student = User.objects.create_user(
            username='STU-901', password='TestStudent123!', role='STUDENT',
        )
        self.client.force_login(student)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_merged_class_section_appears_once_in_teacher_directory(self):
        teacher = User.objects.create_user('T-902', password='TestTeacher123!', role='LECTURER')
        today = timezone.localdate()
        term = AcademicTerm.objects.create(name='Test term', start_date=today - timedelta(days=3),
                                            end_date=today + timedelta(days=60), is_active=True)
        programme = Programme.objects.create(code='TEST', name='Test programme')
        a = ClassGroup.objects.create(code='A-1', programme=programme, term=term, semester_number=1)
        b = ClassGroup.objects.create(code='B-1', programme=programme, term=term, semester_number=1)
        subject = Subject.objects.create(code='ENG-901', name='English', short_name='Eng')
        offering = ClassSubject.objects.create(class_group=a, subject=subject, lecturer=teacher)
        offering.class_groups.add(a, b)
        response = self.client.get(self.url)
        row = next(x for x in response.context['rows'] if x['teacher'].pk == teacher.pk)
        self.assertEqual(row['section_count'], 1)
        self.assertEqual(row['merged_count'], 1)
