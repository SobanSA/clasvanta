#!/usr/bin/env python3
"""Upgrade Clasvanta student management.

Adds:
- Activate / deactivate student account.
- Safe delete for students with no protected history.
- Force delete that removes all student-specific attendance/audit/fine/enrolment data.
- Student-management page spacing/padding fixes.

Run from the Django project root (directory containing manage.py).
No database migration is required.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import py_compile
import shutil
import sys

ROOT = Path.cwd()
views_path = ROOT / 'academics' / 'views.py'
list_path = ROOT / 'templates' / 'academics' / 'students_list.html'
manage_path = ROOT / 'templates' / 'academics' / 'student_delete.html'
test_path = ROOT / 'academics' / 'test_student_deletion.py'
css_path = ROOT / 'static' / 'css' / 'student_management.css'

REQUIRED = [ROOT / 'manage.py', views_path, list_path, manage_path]
for path in REQUIRED:
    if not path.exists():
        print(f'ERROR: required file not found: {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}')
        print('Run this installer from the attendance_app directory containing manage.py.')
        sys.exit(1)

views = views_path.read_text(encoding='utf-8')
students_list = list_path.read_text(encoding='utf-8')
manage_template_existing = manage_path.read_text(encoding='utf-8')

if "action == 'force_delete'" in views and 'student-force-delete-panel' in manage_template_existing:
    print('Student management v2 is already installed. No changes required.')
    sys.exit(0)

start_marker = "@role_required('ADMIN')\n@require_http_methods(['GET', 'POST'])\ndef student_delete(request, student_id):"
end_marker = "\n\n@role_required('ADMIN')\ndef student_attendance(request):"
if start_marker not in views or end_marker not in views:
    print('ERROR: existing controlled student-deletion feature was not found in academics/views.py.')
    print('Install the previous student deletion feature first, or send academics/views.py to ChatGPT.')
    sys.exit(1)

# SessionDeletionAudit is needed to scrub target-student data from immutable
# deleted-session snapshots during an explicitly requested force delete.
if 'from attendance.models import SessionDeletionAudit\n' not in views:
    protected_import = 'from django.db.models.deletion import ProtectedError\n'
    if protected_import not in views:
        print('ERROR: ProtectedError import from the previous student-delete feature was not found.')
        sys.exit(1)
    views = views.replace(
        protected_import,
        protected_import + 'from attendance.models import SessionDeletionAudit\n',
        1,
    )

new_view = r'''@role_required('ADMIN')
@require_http_methods(['GET', 'POST'])
def student_delete(request, student_id):
    """Manage student status, safe deletion, and explicitly confirmed force deletion."""
    student = get_object_or_404(
        StudentProfile.objects.select_related('user'), pk=student_id,
    )

    def snapshot_entry_matches(entry, *, profile_id, registration):
        if not isinstance(entry, dict):
            return False
        entry_student_id = entry.get('student_id')
        entry_registration = str(entry.get('registration_number') or '').strip()
        return (
            str(entry_student_id) == str(profile_id)
            or (entry_registration and entry_registration.casefold() == registration.casefold())
        )

    def snapshot_entry_count(profile_id, registration):
        count = 0
        for deletion in SessionDeletionAudit.objects.only('snapshot'):
            snapshot = deletion.snapshot or {}
            count += sum(
                snapshot_entry_matches(item, profile_id=profile_id, registration=registration)
                for item in (snapshot.get('records') or [])
            )
            count += sum(
                snapshot_entry_matches(item, profile_id=profile_id, registration=registration)
                for item in (snapshot.get('attendance_audits') or [])
            )
        return count

    memberships = list(
        ClassMembership.objects.filter(student=student)
        .select_related('term', 'class_group__programme')
        .order_by('-term__start_date', '-pk')
    )
    attendance_count = AttendanceRecord.objects.filter(student=student).count()
    audit_count = AttendanceAudit.objects.filter(student=student).count()
    fine_entry_count = FineLedgerEntry.objects.filter(student=student).count()
    snapshot_count = snapshot_entry_count(student.pk, student.user.username)
    can_delete = (attendance_count + audit_count + fine_entry_count + snapshot_count) == 0

    if request.method == 'POST':
        action = request.POST.get('action', 'safe_delete')
        return_to_list = request.POST.get('return_to') == 'list'

        if action == 'toggle_active':
            with transaction.atomic():
                locked = StudentProfile.objects.select_for_update().select_related('user').get(pk=student.pk)
                user = User.objects.select_for_update().get(pk=locked.user_id)
                user.is_active = not user.is_active
                user.save(update_fields=['is_active'])
                new_status = 'active' if user.is_active else 'inactive'
            messages.success(request, f'Student {user.username} is now {new_status}.')
            return redirect('students_list' if return_to_list else 'student_delete', **({} if return_to_list else {'student_id': student.pk}))

        confirmation = request.POST.get('confirm_registration', '').strip()
        if confirmation.casefold() != student.user.username.casefold():
            messages.error(request, 'Type the exact registration number to confirm this deletion.')
            return redirect('student_delete', student_id=student.pk)

        if action == 'safe_delete':
            if not can_delete:
                messages.error(
                    request,
                    'Safe deletion is blocked because this student has historical records. '
                    'Use Force Delete only if you intentionally want to erase that history.',
                )
                return redirect('student_delete', student_id=student.pk)
            try:
                with transaction.atomic():
                    locked = StudentProfile.objects.select_for_update().select_related('user').get(pk=student.pk)
                    user = User.objects.select_for_update().get(pk=locked.user_id)
                    if (
                        AttendanceRecord.objects.filter(student=locked).exists()
                        or AttendanceAudit.objects.filter(student=locked).exists()
                        or FineLedgerEntry.objects.filter(student=locked).exists()
                        or snapshot_entry_count(locked.pk, user.username)
                    ):
                        raise ValidationError(
                            'Historical records were found while deleting. The student was not deleted.'
                        )
                    registration = user.username
                    ClassMembership.objects.filter(student=locked).delete()
                    locked.delete()
                    user.delete()
                messages.success(request, f'Student {registration} permanently deleted.')
                return redirect('students_list')
            except (ValidationError, ProtectedError) as exc:
                messages.error(request, f'Could not delete student: {exc}')
                return redirect('student_delete', student_id=student.pk)

        if action == 'force_delete':
            phrase = request.POST.get('confirm_phrase', '').strip()
            if phrase != 'FORCE DELETE':
                messages.error(request, 'Type FORCE DELETE exactly to confirm complete history removal.')
                return redirect('student_delete', student_id=student.pk)

            try:
                with transaction.atomic():
                    locked = StudentProfile.objects.select_for_update().select_related('user').get(pk=student.pk)
                    user = User.objects.select_for_update().get(pk=locked.user_id)
                    registration = user.username

                    # AttendanceAudit PROTECTs AttendanceRecord, so audit rows must go first.
                    deleted_audits = AttendanceAudit.objects.filter(student=locked).delete()[0]
                    deleted_records = AttendanceRecord.objects.filter(student=locked).delete()[0]
                    deleted_fines = FineLedgerEntry.objects.filter(student=locked).delete()[0]

                    # Scrub this student's identity and mark-level history from any
                    # previously saved deleted-session snapshots without deleting
                    # the snapshot/history belonging to other students.
                    scrubbed_snapshot_entries = 0
                    for deletion in SessionDeletionAudit.objects.select_for_update().all():
                        snapshot = dict(deletion.snapshot or {})
                        records = list(snapshot.get('records') or [])
                        audit_rows = list(snapshot.get('attendance_audits') or [])
                        new_records = [
                            item for item in records
                            if not snapshot_entry_matches(
                                item, profile_id=locked.pk, registration=registration,
                            )
                        ]
                        new_audit_rows = [
                            item for item in audit_rows
                            if not snapshot_entry_matches(
                                item, profile_id=locked.pk, registration=registration,
                            )
                        ]
                        removed = (len(records) - len(new_records)) + (len(audit_rows) - len(new_audit_rows))
                        if removed:
                            scrubbed_snapshot_entries += removed
                            snapshot['records'] = new_records
                            snapshot['attendance_audits'] = new_audit_rows
                            deletion.snapshot = snapshot
                            deletion.record_count = len(new_records)
                            deletion.present_count = sum(item.get('status') == AttendanceRecord.PRESENT for item in new_records)
                            deletion.absent_count = sum(item.get('status') == AttendanceRecord.ABSENT for item in new_records)
                            deletion.save(update_fields=[
                                'snapshot', 'record_count', 'present_count', 'absent_count',
                            ])

                    deleted_memberships = ClassMembership.objects.filter(student=locked).delete()[0]
                    locked.delete()
                    user.delete()

                messages.success(
                    request,
                    f'Force deleted student {registration}: '
                    f'{deleted_records} attendance record(s), {deleted_audits} attendance audit row(s), '
                    f'{deleted_fines} fine ledger entry/entries, {deleted_memberships} enrollment record(s), '
                    f'and {scrubbed_snapshot_entries} deleted-session snapshot entry/entries removed.',
                )
                return redirect('students_list')
            except (ValidationError, ProtectedError) as exc:
                messages.error(request, f'Force delete failed and was rolled back: {exc}')
                return redirect('student_delete', student_id=student.pk)

        messages.error(request, 'Unknown student-management action.')
        return redirect('student_delete', student_id=student.pk)

    return render(request, 'academics/student_delete.html', {
        'student': student,
        'memberships': memberships,
        'membership_count': len(memberships),
        'attendance_count': attendance_count,
        'audit_count': audit_count,
        'fine_entry_count': fine_entry_count,
        'snapshot_count': snapshot_count,
        'can_delete': can_delete,
    })'''

start = views.index(start_marker)
end = views.index(end_marker, start)
views = views[:start] + new_view + views[end:]

old_action = '''<td><div class="row-actions"><a class="btn btn-small btn-danger-soft" href="{% url 'student_delete' row.membership.student.pk %}">Delete</a></div></td>'''
new_action = '''<td><div class="row-actions"><form method="post" action="{% url 'student_delete' row.membership.student.pk %}" onsubmit="return confirm('{% if row.membership.student.user.is_active %}Deactivate this student account? The student will no longer be able to sign in.{% else %}Activate this student account?{% endif %}');">{% csrf_token %}<input type="hidden" name="action" value="toggle_active"><input type="hidden" name="return_to" value="list"><button class="btn btn-small {% if row.membership.student.user.is_active %}btn-danger-soft{% else %}btn-primary{% endif %}" type="submit">{% if row.membership.student.user.is_active %}Deactivate{% else %}Activate{% endif %}</button></form><a class="btn btn-small btn-secondary" href="{% url 'student_delete' row.membership.student.pk %}">Manage / Delete</a></div></td>'''
if old_action not in students_list:
    print('ERROR: expected Delete action in Enrolled Students was not found. No files were changed.')
    print('Send templates/academics/students_list.html to ChatGPT.')
    sys.exit(1)
students_list = students_list.replace(old_action, new_action, 1)
students_list = students_list.replace(
    '<span class="status-pill">Disabled</span>',
    '<span class="status-pill">Inactive</span>',
)

manage_template = r'''{% extends 'base.html' %}
{% load static %}
{% block title %}Manage student | {{ app_branding.app_name }}{% endblock %}
{% block crumb %}Students / Manage student{% endblock %}
{% block head %}{{ block.super }}<link rel="stylesheet" href="{% static 'css/student_management.css' %}?v=289">{% endblock %}
{% block content %}
<div class="page-heading student-management-heading">
  <a class="back-link" href="{% url 'students_list' %}">&larr; Back to enrolled students</a>
  <span class="eyebrow">STUDENT MANAGEMENT</span>
  <h1>Manage student</h1>
  <p>Change account status, safely remove an unused student, or explicitly erase all student-specific history.</p>
</div>

<section class="panel student-manage-card">
  <div class="panel-head"><div><h2>{{ student.user.get_full_name|default:student.user.username }}</h2><p class="help-text">Registration: {{ student.user.username }}</p></div><div class="student-manage-statuses">{% if student.user.is_active %}<span class="status-pill done">Active</span>{% else %}<span class="status-pill">Inactive</span>{% endif %}{% if can_delete %}<span class="status-pill done">Safe to delete</span>{% else %}<span class="status-pill absent-pill">Protected history</span>{% endif %}</div></div>
  <div class="student-manage-body">
    <div class="student-manage-grid">
      <div class="student-manage-stat"><span>Registration number</span><strong>{{ student.user.username }}</strong></div>
      <div class="student-manage-stat"><span>Enrollment records</span><strong>{{ membership_count }}</strong></div>
      <div class="student-manage-stat"><span>Attendance records</span><strong>{{ attendance_count }}</strong></div>
      <div class="student-manage-stat"><span>Attendance audit entries</span><strong>{{ audit_count }}</strong></div>
      <div class="student-manage-stat"><span>Fine ledger entries</span><strong>{{ fine_entry_count }}</strong></div>
      <div class="student-manage-stat"><span>Deleted-session snapshot entries</span><strong>{{ snapshot_count }}</strong></div>
    </div>
    <div class="student-manage-account-action">
      <div><strong>Account access</strong><p>{% if student.user.is_active %}The student can currently sign in. Deactivation keeps all records but blocks login.{% else %}The account is inactive. All academic records remain stored.{% endif %}</p></div>
      <form method="post">{% csrf_token %}<input type="hidden" name="action" value="toggle_active"><button class="btn {% if student.user.is_active %}btn-danger-soft{% else %}btn-primary{% endif %}" type="submit">{% if student.user.is_active %}Set student inactive{% else %}Activate student{% endif %}</button></form>
    </div>
  </div>
</section>

{% if memberships %}
<section class="panel student-manage-card">
  <div class="panel-head"><div><h2>Enrollment history</h2><p class="help-text">These memberships are retained while the student exists.</p></div></div>
  <div class="table-scroller"><table class="data-table"><thead><tr><th>Term</th><th>Programme</th><th>Class</th></tr></thead><tbody>
  {% for membership in memberships %}<tr><td>{{ membership.term.name }}</td><td>{{ membership.class_group.programme.code }}</td><td><strong>{{ membership.class_group.code }}</strong><small>{{ membership.class_group.name }}</small></td></tr>{% endfor %}
  </tbody></table></div>
</section>
{% endif %}

{% if can_delete %}
<section class="panel student-manage-card student-safe-delete-panel">
  <div class="panel-head"><div><h2>Permanent deletion</h2><p class="help-text">No attendance, audit, fine, or deleted-session snapshot history was found for this student.</p></div><span class="status-pill done">Safe delete</span></div>
  <div class="student-manage-body">
    <div class="student-delete-warning"><strong>This action cannot be undone.</strong><span>The student login, profile and all enrollment records will be permanently removed.</span></div>
    <form method="post" class="student-delete-form">{% csrf_token %}<input type="hidden" name="action" value="safe_delete"><div class="form-field"><label for="confirmRegistration">Type registration number <strong>{{ student.user.username }}</strong> to confirm</label><input id="confirmRegistration" name="confirm_registration" autocomplete="off" required></div><div class="hero-actions"><button class="btn btn-danger" type="submit">Permanently delete student</button><a class="btn btn-secondary" href="{% url 'students_list' %}">Cancel</a></div></form>
  </div>
</section>
{% else %}
<section class="panel student-manage-card student-protected-panel">
  <div class="panel-head"><div><h2>Safe deletion blocked</h2><p class="help-text">Historical student data exists, so normal deletion remains protected.</p></div><span class="status-pill absent-pill">{{ attendance_count|add:audit_count|add:fine_entry_count|add:snapshot_count }} protected item{{ attendance_count|add:audit_count|add:fine_entry_count|add:snapshot_count|pluralize }}</span></div>
  <div class="student-manage-body"><p class="student-manage-copy">You can keep the student inactive and preserve history, or use Force Delete below if the records were created in error and must be completely removed.</p></div>
</section>

<section class="panel student-manage-card student-force-delete-panel">
  <div class="panel-head"><div><span class="eyebrow">DESTRUCTIVE ACTION</span><h2>Force delete student and all records</h2><p class="help-text">This deliberately overrides the normal historical-record protection.</p></div></div>
  <div class="student-manage-body">
    <div class="student-force-delete-summary"><strong>This will permanently erase:</strong><ul><li>{{ attendance_count }} attendance record{{ attendance_count|pluralize }}</li><li>{{ audit_count }} student-level attendance audit entr{{ audit_count|pluralize:"y,ies" }}</li><li>{{ fine_entry_count }} fine ledger entr{{ fine_entry_count|pluralize:"y,ies" }}</li><li>{{ membership_count }} enrollment record{{ membership_count|pluralize }}</li><li>{{ snapshot_count }} deleted-session snapshot entr{{ snapshot_count|pluralize:"y,ies" }}</li><li>the student profile and login account</li></ul><p>Lecture sessions and records belonging to other students are not deleted. <strong>Take a database backup before using Force Delete if there is any chance you may need this student data later.</strong></p></div>
    <form method="post" class="student-delete-form" onsubmit="return confirm('FORCE DELETE will permanently erase this student and their student-specific history. Continue?');">{% csrf_token %}<input type="hidden" name="action" value="force_delete"><div class="student-delete-confirm-grid"><div class="form-field"><label for="forceRegistration">Type registration number <strong>{{ student.user.username }}</strong></label><input id="forceRegistration" name="confirm_registration" autocomplete="off" required></div><div class="form-field"><label for="forcePhrase">Type <strong>FORCE DELETE</strong></label><input id="forcePhrase" name="confirm_phrase" autocomplete="off" required></div></div><button class="btn btn-danger" type="submit">Force delete student and all records</button></form>
  </div>
</section>
{% endif %}
{% endblock %}
'''

css_content = r'''/* Clasvanta student management / destructive-action page */
.student-management-heading .back-link{display:block;width:max-content;max-width:100%;margin-bottom:12px}
.student-management-heading .eyebrow{display:block;margin-bottom:8px}
.student-manage-card{overflow:hidden}
.student-manage-card+.student-manage-card{margin-top:18px}
.student-manage-card>.panel-head{padding:22px 28px}
.student-manage-statuses{display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap}
.student-manage-body{padding:22px 28px 26px}
.student-manage-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 28px}
.student-manage-stat{min-width:0;padding:14px 0;border-bottom:1px solid #eef1f5}
.student-manage-stat span,.student-manage-stat strong{display:block;overflow-wrap:anywhere}
.student-manage-stat span{font-size:9px;color:var(--muted);text-transform:uppercase;font-weight:800;letter-spacing:.035em}
.student-manage-stat strong{margin-top:4px;font-size:13px;color:var(--ink)}
.student-manage-account-action{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-top:22px;padding:17px 18px;border:1px solid var(--line);border-radius:11px;background:#fbfcfe}
.student-manage-account-action>div{min-width:0}
.student-manage-account-action strong{display:block;font-size:12px;color:var(--ink)}
.student-manage-account-action p,.student-manage-copy{margin:4px 0 0;color:var(--muted);font-size:10px;line-height:1.6}
.student-manage-account-action form{flex:0 0 auto;margin:0}
.student-delete-warning{display:grid;gap:4px;margin-bottom:18px;padding:14px 16px;border:1px solid #f0c8cd;border-radius:10px;background:#fff3f4;color:#a83c49}
.student-delete-warning strong{font-size:11px}.student-delete-warning span{font-size:10px;line-height:1.55}
.student-delete-form{display:grid;gap:16px}
.student-delete-form .form-field{min-width:0}
.student-delete-confirm-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.student-protected-panel{border-color:#efd9b1}
.student-force-delete-panel{border-color:#efbfc6}
.student-force-delete-panel>.panel-head{background:#fff8f8;border-bottom-color:#f4d8dc}
.student-force-delete-summary{margin-bottom:18px;padding:16px 18px;border:1px solid #f1c9ce;border-radius:10px;background:#fff5f6;color:#8f3642}
.student-force-delete-summary strong{display:block;margin-bottom:8px;font-size:11px}
.student-force-delete-summary ul{margin:0 0 10px 18px;padding:0;font-size:10px;line-height:1.75}
.student-force-delete-summary p{margin:0;font-size:10px;line-height:1.55;color:#9a5961}
@media(max-width:760px){
  .student-manage-card>.panel-head{padding:18px}
  .student-manage-body{padding:18px}
  .student-manage-grid,.student-delete-confirm-grid{grid-template-columns:1fr}
  .student-manage-account-action{align-items:flex-start;flex-direction:column}
  .student-manage-account-action form,.student-manage-account-action .btn,.student-delete-form>.btn{width:100%}
  .student-manage-statuses{justify-content:flex-start}
}
'''

test_content = r'''from decimal import Decimal
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
'''

stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
backup = ROOT / f'.student_management_v2_backup_{stamp}'
backup.mkdir()
for path in (views_path, list_path, manage_path, test_path, css_path):
    if path.exists():
        dest = backup / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)

views_path.write_text(views, encoding='utf-8')
list_path.write_text(students_list, encoding='utf-8')
manage_path.write_text(manage_template, encoding='utf-8')
test_path.write_text(test_content, encoding='utf-8')
css_path.parent.mkdir(parents=True, exist_ok=True)
css_path.write_text(css_content, encoding='utf-8')

try:
    py_compile.compile(str(views_path), doraise=True)
    py_compile.compile(str(test_path), doraise=True)
except Exception as exc:
    print(f'ERROR: Python syntax validation failed: {exc}')
    print(f'Backup is available at: {backup.name}')
    sys.exit(1)

print('SUCCESS: student management v2 installed.')
print(f'Backup created: {backup.name}')
print('Next commands:')
print('  python manage.py check')
print('  python manage.py test academics.test_student_deletion')
print('  python manage.py collectstatic --noinput')
print('Then restart the Plesk Python application.')
