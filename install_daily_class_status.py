#!/usr/bin/env python3
"""Safe installer for Clasvanta daily class status + dashboard make-up counter fix.

Run from the project root (directory containing manage.py):
    source .venv/bin/activate
    python install_daily_class_status.py

No database migration is required.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import py_compile
import shutil
import sys

ROOT = Path.cwd().resolve()

PATHS = {
    'academics/views.py': ROOT / 'academics' / 'views.py',
    'attendance/views.py': ROOT / 'attendance' / 'views.py',
    'templates/admin_panel/dashboard.html': ROOT / 'templates' / 'admin_panel' / 'dashboard.html',
    'templates/attendance/admin_sessions.html': ROOT / 'templates' / 'attendance' / 'admin_sessions.html',
    'templates/base.html': ROOT / 'templates' / 'base.html',
    'static/css/admin_usability.css': ROOT / 'static' / 'css' / 'admin_usability.css',
}

for rel, path in PATHS.items():
    if not path.exists():
        print(f'ERROR: required file not found: {rel}')
        print('Run this installer from the attendance_app directory containing manage.py.')
        sys.exit(1)
if not (ROOT / 'manage.py').exists():
    print('ERROR: manage.py was not found. Run from the attendance_app project root.')
    sys.exit(1)


def replace_block(text, start_marker, end_marker, replacement, label):
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f'Could not find start marker for {label}.')
    end = text.find(end_marker, start + len(start_marker))
    if end < 0:
        raise RuntimeError(f'Could not find end marker for {label}.')
    return text[:start] + replacement.rstrip() + '\n\n\n' + text[end:]


def replace_once(text, old, new, label):
    count = text.count(old)
    if count == 0:
        raise RuntimeError(f'Could not find expected code for {label}.')
    if count > 1:
        raise RuntimeError(f'Found more than one match for {label}; installer stopped safely.')
    return text.replace(old, new, 1)


# academics/views.py — dashboard counts
academic_path = PATHS['academics/views.py']
academics = academic_path.read_text(encoding='utf-8')
if 'from calendar import monthrange\n' not in academics:
    if 'import csv\n' not in academics:
        raise RuntimeError('Could not find import anchor in academics/views.py.')
    academics = academics.replace('import csv\n', 'import csv\nfrom calendar import monthrange\n', 1)

admin_dashboard = r"""@role_required('ADMIN')
def admin_dashboard(request):
    today = timezone.localdate()
    month_start = today.replace(day=1)
    month_end = today.replace(day=monthrange(today.year, today.month)[1])
    active = AcademicTerm.objects.filter(is_active=True).first()

    today_scheduled = 0
    today_held = 0
    makeup_today = 0
    makeup_month = 0
    makeup_month_start = None
    makeup_month_end = None

    if active:
        term_scope = (
            Q(class_subject__class_groups__term=active) |
            Q(
                class_subject__class_group__term=active,
                class_subject__class_groups__isnull=True,
            )
        )

        active_makeups = MakeupClass.objects.filter(
            term_scope,
            status=MakeupClass.APPROVED,
        ).distinct()

        # Full current month, constrained to the active term. This deliberately
        # includes approved future make-ups later in the same calendar month.
        makeup_month_start = max(month_start, active.start_date)
        makeup_month_end = min(month_end, active.end_date)
        if makeup_month_start <= makeup_month_end:
            makeup_month = active_makeups.filter(
                lecture_date__range=(makeup_month_start, makeup_month_end),
            ).count()

        if active.start_date <= today <= active.end_date:
            today_regular = WeeklySchedule.objects.filter(
                term_scope,
                weekday=today.weekday(),
            ).distinct()
            regular_keys = set(
                today_regular.values_list('class_subject_id', 'lecture_number')
            )

            today_makeups = active_makeups.filter(lecture_date=today)
            makeup_keys = set(
                today_makeups.values_list('class_subject_id', 'lecture_number')
            )
            makeup_today = len(makeup_keys)

            # Match the detail screen: regular + approved make-up occurrences.
            scheduled_keys = regular_keys | makeup_keys
            held_keys = set(
                LectureSession.objects.filter(
                    lecture_date=today,
                    status='SUBMITTED',
                    class_subject_id__in={key[0] for key in scheduled_keys},
                ).values_list('class_subject_id', 'lecture_number')
            ) if scheduled_keys else set()
            today_scheduled = len(scheduled_keys)
            today_held = len(scheduled_keys & held_keys)

    context = {
        'student_count': StudentProfile.objects.count(),
        'lecturer_count': User.objects.filter(role='LECTURER', is_active=True).count(),
        'class_count': ClassGroup.objects.filter(term__is_active=True).count(),
        'today_sessions': today_held,
        'today_scheduled': today_scheduled,
        'today_held': today_held,
        'makeup_today': makeup_today,
        'makeup_month': makeup_month,
        'makeup_month_start': makeup_month_start,
        'makeup_month_end': makeup_month_end,
        'month_start': month_start,
        'recent_sessions': LectureSession.objects.select_related(
            'class_subject__class_group', 'class_subject__subject', 'class_subject__lecturer', 'submitted_by'
        ).order_by('-submitted_at')[:8],
        'recent_audits': AttendanceAudit.objects.select_related(
            'actor', 'student__user', 'session__class_subject__subject'
        ).order_by('-created_at')[:6],
        'active_terms': AcademicTerm.objects.filter(is_active=True),
    }
    return render(request, 'admin_panel/dashboard.html', context)"""
academics = replace_block(
    academics,
    "@role_required('ADMIN')\ndef admin_dashboard(request):",
    "@role_required('STUDENT')\ndef student_dashboard(request):",
    admin_dashboard,
    'admin_dashboard',
)

# attendance/views.py — daily class status
attendance_path = PATHS['attendance/views.py']
attendance = attendance_path.read_text(encoding='utf-8')

daily_block = r"""def _day_rows(selected_date, active):
    regular = WeeklySchedule.objects.none()
    makeups = MakeupClass.objects.none()
    if active and active.start_date <= selected_date <= active.end_date:
        term_scope = (
            Q(class_subject__class_groups__term=active) |
            Q(
                class_subject__class_group__term=active,
                class_subject__class_groups__isnull=True,
            )
        )
        regular = WeeklySchedule.objects.filter(
            term_scope,
            weekday=selected_date.weekday(),
        ).select_related(
            'class_subject__class_group__term', 'class_subject__subject', 'class_subject__lecturer',
        ).prefetch_related('class_subject__class_groups').distinct()
        makeups = MakeupClass.objects.filter(
            term_scope,
            lecture_date=selected_date,
            status=MakeupClass.APPROVED,
        ).select_related(
            'class_subject__class_group__term', 'class_subject__subject', 'class_subject__lecturer',
        ).prefetch_related('class_subject__class_groups').distinct()

    today = timezone.localdate()
    rows = []

    def add_row(*, source, offering, lecture_number, schedule=None, makeup=None):
        count, merged = _student_count(offering)
        session = _session_for(offering.pk, selected_date, lecture_number)
        if session and session.status == 'SUBMITTED':
            state = 'HELD'
            label = 'Held'
        elif session and session.status == 'CANCELLED':
            state = 'CANCELLED'
            label = 'Cancelled'
        elif selected_date < today:
            state = 'MISSED'
            label = 'Missed / Not marked'
        elif selected_date > today:
            state = 'SCHEDULED'
            label = 'Scheduled'
        else:
            state = 'PENDING'
            label = 'Pending'
        rows.append({
            'source': source,
            'schedule': schedule,
            'makeup': makeup,
            'offering': offering,
            'lecture_number': lecture_number,
            'session': session,
            'student_count': count,
            'merged': merged,
            'state': state,
            'state_label': label,
        })

    for sch in regular:
        add_row(
            source='REGULAR', offering=sch.class_subject,
            lecture_number=sch.lecture_number, schedule=sch,
        )
    for makeup in makeups:
        add_row(
            source='MAKEUP', offering=makeup.class_subject,
            lecture_number=makeup.lecture_number, makeup=makeup,
        )

    return sorted(
        rows,
        key=lambda item: (
            item['lecture_number'], item['offering'].subject.name.lower(), item['source'],
        ),
    )


@role_required('ADMIN')
def admin_sessions(request):
    today = timezone.localdate()
    active = AcademicTerm.objects.filter(is_active=True).first()
    today_in_term = bool(active and active.start_date <= today <= active.end_date)
    default_date = today if today_in_term else (active.start_date if active else today)

    raw_date = request.GET.get('date', '').strip()
    selected_date = default_date
    if raw_date:
        try:
            candidate = date.fromisoformat(raw_date)
            if active and not (active.start_date <= candidate <= active.end_date):
                messages.error(
                    request,
                    f'Select a date within the active term ({active.start_date} to {active.end_date}).',
                )
            else:
                selected_date = candidate
        except ValueError:
            messages.error(request, 'Invalid date. Showing the default active-term date instead.')

    date_in_term = bool(active and active.start_date <= selected_date <= active.end_date)
    rows = _day_rows(selected_date, active) if date_in_term else []

    held_count = sum(row['state'] == 'HELD' for row in rows)
    cancelled_count = sum(row['state'] == 'CANCELLED' for row in rows)
    unmarked_count = sum(row['state'] in {'MISSED', 'PENDING', 'SCHEDULED'} for row in rows)
    makeup_count = sum(row['source'] == 'MAKEUP' for row in rows)
    regular_count = sum(row['source'] == 'REGULAR' for row in rows)

    if selected_date < today:
        unmarked_label = 'Missed'
    elif selected_date > today:
        unmarked_label = 'Upcoming'
    else:
        unmarked_label = 'Pending'

    return render(request, 'attendance/admin_sessions.html', {
        'selected_date': selected_date,
        'today': today,
        'today_in_term': today_in_term,
        'is_today': selected_date == today,
        'is_future': selected_date > today,
        'is_past': selected_date < today,
        'schedule_rows': rows,
        'scheduled_count': len(rows),
        'regular_count': regular_count,
        'makeup_count': makeup_count,
        'held_count': held_count,
        'cancelled_count': cancelled_count,
        'unmarked_count': unmarked_count,
        'unmarked_label': unmarked_label,
        'pending_count': unmarked_count,
        'active_term': active,
        'date_in_term': date_in_term,
        'super_admin': request.user.is_superuser,
    })"""
attendance = replace_block(
    attendance,
    'def _day_rows(selected_date, active):',
    "@role_required('ADMIN', 'LECTURER')\n@require_http_methods(['GET', 'POST'])\ndef makeup_classes(request):",
    daily_block,
    'daily class status views',
)

# dashboard template
dash_path = PATHS['templates/admin_panel/dashboard.html']
dash = dash_path.read_text(encoding='utf-8')
old_card = '<article class="metric-card"><span>Scheduled / Held today</span><strong class="metric-pair"><span>{{ today_scheduled }}</span><em>/</em><span>{{ today_held }}</span></strong><small>Regular timetable · Scheduled / Held</small><div class="metric-glyph">✓</div></article>'
new_card = '<a class="metric-card metric-card-link" href="{% url \'admin_sessions\' %}" aria-label="Open today\'s daily class status"><span>Scheduled / Held today</span><strong class="metric-pair"><span>{{ today_scheduled }}</span><em>/</em><span>{{ today_held }}</span></strong><small>Regular + approved make-up · View details →</small><div class="metric-glyph">✓</div></a>'
if old_card in dash:
    dash = replace_once(dash, old_card, new_card, 'Scheduled / Held dashboard card')
elif 'metric-card-link' not in dash:
    raise RuntimeError('Dashboard Scheduled / Held card did not match the expected version.')

old_month = '<article class="metric-card"><span>Make-up classes this month</span><strong>{{ makeup_month }}</strong><small>Approved from {{ month_start|date:\'1 M\' }} to today</small><div class="metric-glyph">◫</div></article>'
new_month = '<article class="metric-card"><span>Make-up classes this month</span><strong>{{ makeup_month }}</strong><small>{% if makeup_month_start and makeup_month_end %}Approved {{ makeup_month_start|date:\'j M\' }} – {{ makeup_month_end|date:\'j M\' }} within active term{% else %}No active-term dates this month{% endif %}</small><div class="metric-glyph">◫</div></article>'
if old_month in dash:
    dash = replace_once(dash, old_month, new_month, 'Make-up month dashboard card')
elif 'within active term' not in dash:
    raise RuntimeError('Dashboard make-up month card did not match the expected version.')

old_quick = '<a class="quick-card" href="{% url \'admin_sessions\' %}"><div class="quick-icon orange">☑</div><strong>Attendance</strong><small>Review and correct records</small><span>→</span></a>'
new_quick = '<a class="quick-card" href="{% url \'admin_sessions\' %}"><div class="quick-icon orange">☑</div><strong>Daily class status</strong><small>Held, missed, cancelled and make-up classes by date</small><span>→</span></a>'
if old_quick in dash:
    dash = replace_once(dash, old_quick, new_quick, 'dashboard quick action')

# sidebar
base_path = PATHS['templates/base.html']
base = base_path.read_text(encoding='utf-8')
old_nav = '   <a href="{% url \'admin_sessions\' %}"><span class="nav-icon">☑</span> Attendance</a>'
new_nav = '   <a href="{% url \'admin_sessions\' %}" class="{% if request.resolver_match.url_name == \'admin_sessions\' %}active{% endif %}"><span class="nav-icon">☑</span> Daily class status</a>'
if old_nav in base:
    base = replace_once(base, old_nav, new_nav, 'admin sidebar attendance link')
elif 'Daily class status</a>' not in base:
    raise RuntimeError('Admin sidebar Attendance link did not match the expected version.')

# full daily status template
status_template = r"""{% extends 'base.html' %}
{% block title %}Daily class status | {{ app_branding.app_name }}{% endblock %}
{% block crumb %}Daily class status{% endblock %}
{% block content %}
<div class="page-heading heading-row">
  <div>
    <span class="eyebrow">ATTENDANCE MANAGEMENT</span>
    <h1>{% if is_today %}Today's class status{% else %}Class status for {{ selected_date|date:"j F Y" }}{% endif %}</h1>
    <p>Held means attendance was submitted. Past scheduled classes with no attendance are shown as Missed / Not marked. Approved make-up classes are included.</p>
  </div>
  <div class="hero-actions">
    <a class="btn btn-secondary" href="{% url 'makeup_classes' %}">Make-up classes</a>
    <a class="btn btn-secondary" href="{% url 'audit_log' %}">Attendance audit →</a>
  </div>
</div>

{% if not active_term %}
<div class="alert alert-error">No active academic term.</div>
{% else %}
<section class="panel attendance-date-panel daily-status-date-panel">
  <form method="get" class="attendance-date-form">
    <div>
      <label for="attendanceDate">Select date</label>
      <input id="attendanceDate" type="date" name="date"
             value="{{ selected_date|date:'Y-m-d' }}"
             min="{{ active_term.start_date|date:'Y-m-d' }}"
             max="{{ active_term.end_date|date:'Y-m-d' }}">
      <small>{{ active_term.name }} · {{ active_term.start_date|date:"j M Y" }} – {{ active_term.end_date|date:"j M Y" }}</small>
    </div>
    <button class="btn btn-primary" type="submit">Show classes</button>
    {% if today_in_term and not is_today %}<a class="btn btn-secondary" href="{% url 'admin_sessions' %}">Today</a>{% endif %}
  </form>
</section>
{% endif %}

<div class="attendance-day-summary daily-status-summary">
  <div class="metric-card compact"><span>Scheduled</span><strong>{{ scheduled_count }}</strong><small>{{ regular_count }} regular + {{ makeup_count }} make-up</small></div>
  <div class="metric-card compact"><span>Held</span><strong>{{ held_count }}</strong><small>Attendance submitted</small></div>
  <div class="metric-card compact"><span>{{ unmarked_label }}</span><strong>{{ unmarked_count }}</strong><small>{% if is_past %}Past classes not marked{% elif is_future %}Not due yet{% else %}Not marked yet{% endif %}</small></div>
  <div class="metric-card compact"><span>Cancelled</span><strong>{{ cancelled_count }}</strong><small>Explicitly cancelled</small></div>
  <div class="metric-card compact"><span>Make-up</span><strong>{{ makeup_count }}</strong><small>Approved one-off classes</small></div>
</div>

<section class="panel">
  <div class="panel-head">
    <div>
      <h2>{{ selected_date|date:"l, j F Y" }}</h2>
      <p class="help-text">Regular timetable and approved make-up classes for this date.</p>
    </div>
    <strong>{{ scheduled_count }}</strong>
  </div>
  <div class="table-scroller">
    <table class="data-table attendance-schedule-table">
      <thead><tr><th>Lecture</th><th>Course</th><th>Class</th><th>Teacher</th><th>Students</th><th>Type</th><th>Status</th><th>Action</th></tr></thead>
      <tbody>
      {% for row in schedule_rows %}
        <tr>
          <td><strong>L{{ row.lecture_number }}</strong></td>
          <td><strong>{{ row.offering.subject.name }}</strong><small>{{ row.offering.subject.code }}</small></td>
          <td><strong>{{ row.offering.class_codes_display }}</strong>{% if row.merged %}<small>Merged section</small>{% endif %}</td>
          <td>{% if row.offering.lecturer %}{{ row.offering.lecturer.get_full_name|default:row.offering.lecturer.username }}<small>{{ row.offering.lecturer.username }}</small>{% else %}<span class="warning-text">No teacher assigned</span>{% endif %}</td>
          <td>{{ row.student_count }}</td>
          <td>{% if row.source == 'MAKEUP' %}<span class="status-pill makeup-pill">Make-up</span>{% else %}<span class="muted">Regular</span>{% endif %}</td>
          <td>
            {% if row.state == 'HELD' %}<span class="status-pill done">Held</span>{% if row.session %}<small>{{ row.session.submitted_at|date:"H:i" }}</small>{% endif %}
            {% elif row.state == 'CANCELLED' %}<span class="status-pill status-cancelled">Cancelled</span>
            {% elif row.state == 'MISSED' %}<span class="status-pill absent-pill">Missed / Not marked</span>
            {% elif row.state == 'SCHEDULED' %}<span class="status-pill student-scheduled">Scheduled</span>
            {% else %}<span class="status-pill pending">Pending</span>{% endif %}
          </td>
          <td><div class="row-actions">
            {% if row.session %}
              <a class="btn btn-small" href="{% url 'session_detail' row.session.pk %}">{% if row.state == 'HELD' %}View / Correct{% else %}View{% endif %}</a>
              {% if super_admin and row.state == 'HELD' %}<a class="btn btn-small btn-danger" href="{% url 'delete_session' row.session.pk %}">Delete</a>{% endif %}
            {% elif is_future %}
              <span class="muted">Future date</span>
            {% elif row.source == 'MAKEUP' %}
              <a class="btn btn-small btn-primary" href="{% url 'mark_makeup' row.makeup.pk %}">Mark attendance</a>
            {% else %}
              <a class="btn btn-small btn-primary" href="{% url 'admin_new_session' %}?offering={{ row.offering.pk }}&day={{ selected_date|date:'Y-m-d' }}&number={{ row.lecture_number }}">Mark attendance</a>
            {% endif %}
            {% if not is_future and not row.session %}
              <form method="post" action="{% url 'cancel_occurrence' %}" class="inline-action-form" onsubmit="return confirm('Mark this class as cancelled?');">
                {% csrf_token %}<input type="hidden" name="offering" value="{{ row.offering.pk }}"><input type="hidden" name="day" value="{{ selected_date|date:'Y-m-d' }}"><input type="hidden" name="number" value="{{ row.lecture_number }}"><button class="btn btn-small btn-danger-soft" type="submit">Class cancelled</button>
              </form>
            {% endif %}
          </div></td>
        </tr>
      {% empty %}
        <tr><td colspan="8" class="empty-cell">No regular or approved make-up classes are scheduled for {{ selected_date|date:"l, j F Y" }}.</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</section>
{% endblock %}
"""

# CSS append
css_path = PATHS['static/css/admin_usability.css']
css = css_path.read_text(encoding='utf-8')
css_marker = '/* Daily class status dashboard/detail enhancements */'
if css_marker not in css:
    css += r"""

/* Daily class status dashboard/detail enhancements */
.metric-card-link{display:block;color:inherit;text-decoration:none;transition:transform .15s ease,border-color .15s ease,box-shadow .15s ease}
.metric-card-link:hover{text-decoration:none;color:inherit;transform:translateY(-2px);border-color:#c9d8ec;box-shadow:0 8px 28px rgba(20,45,85,.08)}
.daily-status-summary{grid-template-columns:repeat(5,minmax(0,1fr))}
.daily-status-date-panel .attendance-date-form>div{display:grid;gap:5px}
.daily-status-date-panel .attendance-date-form small{font-size:10px;color:var(--muted)}
@media(max-width:1100px){.daily-status-summary{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:760px){.daily-status-summary{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:430px){.daily-status-summary{grid-template-columns:1fr}}
"""

# tests
test_rel = 'attendance/test_daily_class_status.py'
test_path = ROOT / test_rel
test_content = r"""from calendar import monthrange
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
"""

new_contents = {
    'academics/views.py': academics,
    'attendance/views.py': attendance,
    'templates/admin_panel/dashboard.html': dash,
    'templates/attendance/admin_sessions.html': status_template,
    'templates/base.html': base,
    'static/css/admin_usability.css': css,
    test_rel: test_content,
}

if test_path.exists():
    existing_test = test_path.read_text(encoding='utf-8')
    if 'class DailyClassStatusTests' not in existing_test:
        raise RuntimeError(f'{test_rel} already exists and was not created by this feature.')

changed = []
for rel, new in new_contents.items():
    path = ROOT / rel
    old = path.read_text(encoding='utf-8') if path.exists() else None
    if old != new:
        changed.append(rel)

if not changed:
    print('Daily class status feature is already installed. No changes required.')
    sys.exit(0)

stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
backup_root = ROOT / f'.daily_class_status_backup_{stamp}'
backup_root.mkdir(parents=True, exist_ok=False)

for rel in changed:
    path = ROOT / rel
    if path.exists():
        backup = backup_root / rel
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)

try:
    for rel in changed:
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_contents[rel], encoding='utf-8', newline='')
    for rel in ('academics/views.py', 'attendance/views.py', test_rel):
        py_compile.compile(str(ROOT / rel), doraise=True)
except Exception as exc:
    print('INSTALL FAILED. Restoring backups...')
    for rel in changed:
        backup = backup_root / rel
        target = ROOT / rel
        if backup.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
        elif target.exists() and rel == test_rel:
            target.unlink()
    print('ERROR:', exc)
    sys.exit(2)

print('SUCCESS: daily class status + make-up dashboard counter fix installed.')
print('Backup directory:', backup_root.name)
print('Changed/created files:')
for rel in changed:
    print(' -', rel)
print()
print('NEXT COMMANDS:')
print('  python manage.py check')
print('  DJANGO_SETTINGS_MODULE=config.test_settings python manage.py test attendance.test_daily_class_status')
print('  python manage.py collectstatic --noinput')
print('Then restart the Python application in Plesk.')
print('No database migration is required.')
