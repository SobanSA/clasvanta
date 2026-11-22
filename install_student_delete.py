#!/usr/bin/env python3
"""Safe installer for Clasvanta controlled student deletion.

Run from the Django project root (the directory containing manage.py).
No database migration is required.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import py_compile
import shutil
import sys

ROOT = Path.cwd()
REQUIRED = [
    ROOT / 'manage.py',
    ROOT / 'academics' / 'views.py',
    ROOT / 'config' / 'urls.py',
    ROOT / 'templates' / 'academics' / 'students_list.html',
]

for path in REQUIRED:
    if not path.exists():
        try:
            label = path.relative_to(ROOT)
        except ValueError:
            label = path
        print(f'ERROR: required file not found: {label}')
        print('Run this installer from the attendance_app directory containing manage.py.')
        sys.exit(1)

views_path = ROOT / 'academics' / 'views.py'
urls_path = ROOT / 'config' / 'urls.py'
list_path = ROOT / 'templates' / 'academics' / 'students_list.html'
confirm_path = ROOT / 'templates' / 'academics' / 'student_delete.html'
test_path = ROOT / 'academics' / 'test_student_deletion.py'

views = views_path.read_text(encoding='utf-8')
urls = urls_path.read_text(encoding='utf-8')
students_list = list_path.read_text(encoding='utf-8')

if "def student_delete(request, student_id):" in views and "name='student_delete'" in urls:
    print('Controlled student deletion is already installed. No changes required.')
    sys.exit(0)


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f'{label}: expected exactly 1 matching code block, found {count}. No files were changed.'
        )
    return text.replace(old, new, 1)

try:
    views = replace_once(
        views,
        "from django.db import IntegrityError, transaction\n",
        "from django.db import IntegrityError, transaction\nfrom django.db.models.deletion import ProtectedError\n",
        'academics/views.py import',
    )

    anchor = """    return render(request, 'academics/students_list.html', {\n        'active_term': active,\n        'programmes': programmes,\n        'groups': groups,\n        'selected_programme': selected_programme,\n        'selected_class': selected_class,\n        'rows': rows,\n        'student_count': len(rows),\n    })\n\n\n@role_required('ADMIN')\ndef student_attendance(request):\n"""
    insertion = """    return render(request, 'academics/students_list.html', {\n        'active_term': active,\n        'programmes': programmes,\n        'groups': groups,\n        'selected_programme': selected_programme,\n        'selected_class': selected_class,\n        'rows': rows,\n        'student_count': len(rows),\n    })\n\n\n@role_required('ADMIN')\n@require_http_methods(['GET', 'POST'])\ndef student_delete(request, student_id):\n    \"\"\"Safely delete a student account only when no historical records exist.\"\"\"\n    student = get_object_or_404(\n        StudentProfile.objects.select_related('user'), pk=student_id,\n    )\n    memberships = list(\n        ClassMembership.objects.filter(student=student)\n        .select_related('term', 'class_group__programme')\n        .order_by('-term__start_date', '-pk')\n    )\n    attendance_count = AttendanceRecord.objects.filter(student=student).count()\n    audit_count = AttendanceAudit.objects.filter(student=student).count()\n    fine_entry_count = FineLedgerEntry.objects.filter(student=student).count()\n    can_delete = (attendance_count + audit_count + fine_entry_count) == 0\n\n    if request.method == 'POST':\n        if not can_delete:\n            messages.error(\n                request,\n                'This student cannot be permanently deleted because attendance, audit, or fine history exists. '\n                'Historical academic records are protected.',\n            )\n        else:\n            confirmation = request.POST.get('confirm_registration', '').strip()\n            if confirmation.casefold() != student.user.username.casefold():\n                messages.error(request, 'Type the exact registration number to confirm permanent deletion.')\n            else:\n                try:\n                    with transaction.atomic():\n                        locked = StudentProfile.objects.select_for_update().select_related('user').get(pk=student.pk)\n                        user = User.objects.select_for_update().get(pk=locked.user_id)\n\n                        # Re-check after locks so a concurrent history write cannot race deletion.\n                        if (\n                            AttendanceRecord.objects.filter(student=locked).exists()\n                            or AttendanceAudit.objects.filter(student=locked).exists()\n                            or FineLedgerEntry.objects.filter(student=locked).exists()\n                        ):\n                            raise ValidationError(\n                                'Historical records were found while deleting. The student was not deleted.'\n                            )\n\n                        registration = user.username\n                        ClassMembership.objects.filter(student=locked).delete()\n                        locked.delete()\n                        user.delete()\n\n                    messages.success(request, f'Student {registration} permanently deleted.')\n                    return redirect('students_list')\n                except (ValidationError, ProtectedError) as exc:\n                    messages.error(request, f'Could not delete student: {exc}')\n\n        return redirect('student_delete', student_id=student.pk)\n\n    return render(request, 'academics/student_delete.html', {\n        'student': student,\n        'memberships': memberships,\n        'membership_count': len(memberships),\n        'attendance_count': attendance_count,\n        'audit_count': audit_count,\n        'fine_entry_count': fine_entry_count,\n        'can_delete': can_delete,\n    })\n\n\n@role_required('ADMIN')\ndef student_attendance(request):\n"""
    views = replace_once(
        views, anchor, insertion, 'academics/views.py student delete insertion'
    )

    urls = replace_once(
        urls,
        "    path('students/add/', academic_views.student_add, name='student_add'),\n",
        "    path('students/add/', academic_views.student_add, name='student_add'),\n"
        "    path('students/<int:student_id>/delete/', academic_views.student_delete, name='student_delete'),\n",
        'config/urls.py route',
    )

    students_list = replace_once(
        students_list,
        '<th>Inherited subjects</th><th>Account</th></tr>',
        '<th>Inherited subjects</th><th>Account</th><th>Actions</th></tr>',
        'students list header',
    )
    account_cell = (
        '<td>{% if row.membership.student.user.is_active %}'
        '<span class="status-pill done">Active</span>{% else %}'
        '<span class="status-pill">Disabled</span>{% endif %}</td></tr>'
    )
    action_cell = (
        '<td>{% if row.membership.student.user.is_active %}'
        '<span class="status-pill done">Active</span>{% else %}'
        '<span class="status-pill">Disabled</span>{% endif %}</td>'
        '<td><div class="row-actions"><a class="btn btn-small btn-danger-soft" '
        'href="{% url \'student_delete\' row.membership.student.pk %}">Delete</a>'
        '</div></td></tr>'
    )
    students_list = replace_once(
        students_list, account_cell, action_cell, 'students list action'
    )
    if 'colspan="6" class="empty-cell">No enrolled students found' not in students_list:
        raise RuntimeError('students list empty-state column marker not found. No files were changed.')
    students_list = students_list.replace(
        'colspan="6" class="empty-cell">No enrolled students found',
        'colspan="7" class="empty-cell">No enrolled students found',
        1,
    )
    if 'colspan="6" class="empty-cell">No students match this search.' not in students_list:
        raise RuntimeError('students list search empty-state column marker not found. No files were changed.')
    students_list = students_list.replace(
        'colspan="6" class="empty-cell">No students match this search.',
        'colspan="7" class="empty-cell">No students match this search.',
        1,
    )
except RuntimeError as exc:
    print(f'ERROR: {exc}')
    print('The installer stopped before changing any files. Send this output to ChatGPT.')
    sys.exit(1)

confirm_template = '''{% extends 'base.html' %}
{% block title %}Delete student | {{ app_branding.app_name }}{% endblock %}
{% block crumb %}Students / Delete student{% endblock %}
{% block content %}
<div class="page-heading">
  <a class="back-link" href="{% url 'students_list' %}">&larr; Back to enrolled students</a>
  <span class="eyebrow">STUDENT MANAGEMENT</span>
  <h1>Delete student</h1>
  <p>Permanent deletion is available only when the student has no attendance, audit, or fine history.</p>
</div>

<section class="panel">
  <div class="panel-head"><div><h2>{{ student.user.get_full_name|default:student.user.username }}</h2><p class="help-text">Registration: {{ student.user.username }}</p></div>{% if can_delete %}<span class="status-pill done">Safe to delete</span>{% else %}<span class="status-pill absent-pill">Protected history</span>{% endif %}</div>
  <div class="student-profile-fields">
    <div><span>Registration number</span><strong>{{ student.user.username }}</strong></div>
    <div><span>Enrollment records</span><strong>{{ membership_count }}</strong></div>
    <div><span>Attendance records</span><strong>{{ attendance_count }}</strong></div>
    <div><span>Attendance audit entries</span><strong>{{ audit_count }}</strong></div>
    <div><span>Fine ledger entries</span><strong>{{ fine_entry_count }}</strong></div>
    <div><span>Account status</span><strong>{% if student.user.is_active %}Active{% else %}Disabled{% endif %}</strong></div>
  </div>
</section>

{% if memberships %}
<section class="panel">
  <div class="panel-head"><div><h2>Enrollment history</h2><p class="help-text">All memberships will be removed only when permanent deletion is allowed.</p></div></div>
  <div class="table-scroller"><table class="data-table"><thead><tr><th>Term</th><th>Programme</th><th>Class</th></tr></thead><tbody>
  {% for membership in memberships %}<tr><td>{{ membership.term.name }}</td><td>{{ membership.class_group.programme.code }}</td><td><strong>{{ membership.class_group.code }}</strong><small>{{ membership.class_group.name }}</small></td></tr>{% endfor %}
  </tbody></table></div>
</section>
{% endif %}

{% if can_delete %}
<div class="alert alert-error"><strong>This is permanent.</strong> The student account, profile and enrollment records will be deleted. This action cannot be undone.</div>
<section class="panel">
  <form method="post" class="stack-form">{% csrf_token %}
    <div class="form-field"><label for="confirmRegistration">Type registration number <strong>{{ student.user.username }}</strong> to confirm</label><input id="confirmRegistration" name="confirm_registration" autocomplete="off" required></div>
    <div class="hero-actions"><button class="btn btn-danger" type="submit">Permanently delete student</button><a class="btn btn-secondary" href="{% url 'students_list' %}">Cancel</a></div>
  </form>
</section>
{% else %}
<div class="alert alert-error"><strong>Permanent deletion blocked.</strong> This student has historical attendance/audit/fine records. Clasvanta protects those records so attendance and financial history cannot be silently removed.</div>
<div class="hero-actions"><a class="btn btn-secondary" href="{% url 'students_list' %}">Back to students</a></div>
{% endif %}
{% endblock %}
'''

test_content = '''from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from attendance.models import AttendanceRecord, LectureSession
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

    def test_admin_can_delete_student_without_history(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('student_delete', args=[self.student.pk]), {'confirm_registration': 'DEL-001'})
        self.assertRedirects(response, reverse('students_list'))
        self.assertFalse(User.objects.filter(pk=self.student_user.pk).exists())
        self.assertFalse(StudentProfile.objects.filter(pk=self.student.pk).exists())
        self.assertFalse(ClassMembership.objects.filter(student_id=self.student.pk).exists())

    def test_wrong_confirmation_does_not_delete(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('student_delete', args=[self.student.pk]), {'confirm_registration': 'WRONG'})
        self.assertRedirects(response, reverse('student_delete', args=[self.student.pk]))
        self.assertTrue(StudentProfile.objects.filter(pk=self.student.pk).exists())

    def test_attendance_history_blocks_deletion(self):
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
        AttendanceRecord.objects.create(session=session, student=self.student, status='P')
        self.client.force_login(self.admin)
        response = self.client.post(reverse('student_delete', args=[self.student.pk]), {'confirm_registration': 'DEL-001'})
        self.assertRedirects(response, reverse('student_delete', args=[self.student.pk]))
        self.assertTrue(StudentProfile.objects.filter(pk=self.student.pk).exists())

    def test_fine_history_blocks_deletion(self):
        subject = Subject.objects.create(code='DEL-102', name='Fine Subject', short_name='FINE')
        offering = ClassSubject.objects.create(class_group=self.group, subject=subject)
        offering.class_groups.add(self.group)
        FineLedgerEntry.objects.create(
            student=self.student,
            class_subject=offering,
            kind='CHARGE',
            amount=Decimal('100.00'),
            note='Deletion protection test',
            actor=self.admin,
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse('student_delete', args=[self.student.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['can_delete'])
'''

stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
backup = ROOT / f'.student_delete_backup_{stamp}'
backup.mkdir()
for path in (views_path, urls_path, list_path):
    dest = backup / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)

views_path.write_text(views, encoding='utf-8')
urls_path.write_text(urls, encoding='utf-8')
list_path.write_text(students_list, encoding='utf-8')
confirm_path.parent.mkdir(parents=True, exist_ok=True)
confirm_path.write_text(confirm_template, encoding='utf-8')
test_path.write_text(test_content, encoding='utf-8')

try:
    py_compile.compile(str(views_path), doraise=True)
    py_compile.compile(str(urls_path), doraise=True)
    py_compile.compile(str(test_path), doraise=True)
except Exception as exc:
    print(f'ERROR: Python syntax validation failed: {exc}')
    print(f'Backup is available at: {backup.name}')
    sys.exit(1)

print('SUCCESS: controlled student deletion installed.')
print(f'Backup created: {backup.name}')
print('Next run: python manage.py check')
print('Recommended test: python manage.py test academics.test_student_deletion')
print('No database migration is required.')
