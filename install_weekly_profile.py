#!/usr/bin/env python3
"""Safe installer for Clasvanta weekly profile/workload feature (v2.8.5).

Run from the project root (the directory containing manage.py):
    python install_weekly_profile.py

This installer uses only Python's standard library. It validates all expected
anchors before writing, backs up changed files, and does not touch the database.
"""
from pathlib import Path
from datetime import datetime
import py_compile
import shutil
import sys

ROOT = Path.cwd().resolve()

REPLACEMENTS = {'academics/student_portal.py': [('from .models import ClassMembership, ClassSubject, StudentProfile, WeeklySchedule\n', 'from .models import ClassMembership, ClassSubject, StudentProfile, WeeklySchedule\nfrom .workload import weekly_workload_for_offerings\n'), ("@student_required\n@require_GET\ndef profile(request):\n    profile_obj, membership = _student_scope(request.user)\n    assigned_subject_count = len(_assigned_offerings(membership)) if membership else 0\n    return render(request, 'student/profile.html', {\n        'profile': profile_obj,\n        'membership': membership,\n        'assigned_subject_count': assigned_subject_count,\n    })\n", "@student_required\n@require_GET\ndef profile(request):\n    profile_obj, membership = _student_scope(request.user)\n    offerings = _assigned_offerings(membership)\n    assigned_subject_count = len(offerings) if membership else 0\n    weekly = weekly_workload_for_offerings(offerings)\n    return render(request, 'student/profile.html', {\n        'profile': profile_obj,\n        'membership': membership,\n        'assigned_subject_count': assigned_subject_count,\n        'weekly': weekly,\n    })\n")], 'attendance/views.py': [('from academics.models import AcademicTerm, ClassSubject, StudentProfile, WeeklySchedule\n', 'from academics.models import AcademicTerm, ClassSubject, StudentProfile, WeeklySchedule\nfrom academics.workload import weekly_workload_for_lecturer\n'), ("@role_required('LECTURER')\ndef lecturer_dashboard(request):\n    policy, _ = AttendanceSettings.objects.get_or_create(pk=1)\n    return render(request, 'attendance/lecturer_dashboard.html', {\n        'today': timezone.localdate(), 'lectures': _schedule_today(request.user),\n        'policy': policy,\n    })\n\n\ndef _roster_for(offering):\n", "@role_required('LECTURER')\ndef lecturer_dashboard(request):\n    policy, _ = AttendanceSettings.objects.get_or_create(pk=1)\n    return render(request, 'attendance/lecturer_dashboard.html', {\n        'today': timezone.localdate(), 'lectures': _schedule_today(request.user),\n        'policy': policy,\n    })\n\n\n@role_required('LECTURER')\n@require_http_methods(['GET'])\ndef lecturer_profile(request):\n    weekly = weekly_workload_for_lecturer(request.user)\n    return render(request, 'lecturer/profile.html', {\n        'weekly': weekly,\n    })\n\n\ndef _roster_for(offering):\n")], 'config/urls.py': [("    path('lectures/', attendance_views.lecturer_dashboard, name='lecturer_dashboard'),\n", "    path('lectures/', attendance_views.lecturer_dashboard, name='lecturer_dashboard'),\n    path('lecturer/profile/', attendance_views.lecturer_profile, name='lecturer_profile'),\n")], 'templates/base.html': [('<link rel="stylesheet" href="{% static \'css/admin_usability.css\' %}?v=281">\n', '<link rel="stylesheet" href="{% static \'css/admin_usability.css\' %}?v=281">\n<link rel="stylesheet" href="{% static \'css/profile_workload.css\' %}?v=286">\n'), ('   <a href="{% url \'lecturer_dashboard\' %}"><span class="nav-icon">☑</span> Today\'s lectures</a>\n', '   <a href="{% url \'lecturer_dashboard\' %}"><span class="nav-icon">☑</span> Today\'s lectures</a>\n   <a href="{% url \'lecturer_profile\' %}" class="{% if request.resolver_match.url_name == \'lecturer_profile\' %}active{% endif %}"><span class="nav-icon">○</span> My Profile</a>\n')], 'templates/attendance/lecturer_dashboard.html': [('{% block content %}<div class="page-heading heading-row"><div><span class="eyebrow">LECTURER PORTAL</span><h1>Today\'s lectures</h1><p>{{ today|date:\'l, j F Y\' }} · Attendance window {{ policy.working_start|time:\'h:i A\' }} – {{ policy.working_end|time:\'h:i A\' }} (PKT)</p></div><a class="btn btn-secondary" href="{% url \'makeup_classes\' %}">+ Request make-up class</a></div>\n', '{% block content %}<div class="page-heading heading-row"><div><span class="eyebrow">LECTURER PORTAL</span><h1>Today\'s lectures</h1><p>{{ today|date:\'l, j F Y\' }} · Attendance window {{ policy.working_start|time:\'h:i A\' }} – {{ policy.working_end|time:\'h:i A\' }} (PKT)</p></div><div class="hero-actions"><a class="btn btn-secondary" href="{% url \'lecturer_profile\' %}">Weekly workload</a><a class="btn btn-secondary" href="{% url \'makeup_classes\' %}">+ Request make-up class</a></div></div>\n')]}

FULL_FILES = {
    'academics/workload.py': '"""Shared weekly timetable/workload helpers for lecturer and student profiles."""\nfrom django.db.models import Q\n\nfrom .models import AcademicTerm, WeeklySchedule\n\n\ndef _weekly_payload(schedules):\n    days = {\n        weekday: {\'weekday\': weekday, \'label\': label, \'lectures\': []}\n        for weekday, label in WeeklySchedule.DAYS\n    }\n    subject_ids = set()\n    section_ids = set()\n    class_ids = set()\n    lecturer_ids = set()\n    merged_section_ids = set()\n    teaching_days = set()\n\n    for schedule in schedules:\n        offering = schedule.class_subject\n        linked_classes = list(offering.class_groups.all())\n        if not linked_classes and offering.class_group_id:\n            linked_classes = [offering.class_group]\n        linked_classes = sorted(\n            linked_classes,\n            key=lambda group: (group.programme.code, group.semester_number, group.code),\n        )\n        class_codes = \', \'.join(group.code for group in linked_classes)\n        class_count = len(linked_classes)\n\n        days[schedule.weekday][\'lectures\'].append({\n            \'schedule\': schedule,\n            \'offering\': offering,\n            \'lecture_number\': schedule.lecture_number,\n            \'subject\': offering.subject,\n            \'lecturer\': offering.lecturer,\n            \'class_codes\': class_codes,\n            \'class_count\': class_count,\n            \'merged\': class_count > 1,\n        })\n        teaching_days.add(schedule.weekday)\n        subject_ids.add(offering.subject_id)\n        section_ids.add(offering.pk)\n        class_ids.update(group.pk for group in linked_classes)\n        if offering.lecturer_id:\n            lecturer_ids.add(offering.lecturer_id)\n        if class_count > 1:\n            merged_section_ids.add(offering.pk)\n\n    return {\n        \'days\': [days[weekday] for weekday, _ in WeeklySchedule.DAYS],\n        \'summary\': {\n            \'lecture_count\': len(schedules),\n            \'subject_count\': len(subject_ids),\n            \'section_count\': len(section_ids),\n            \'class_count\': len(class_ids),\n            \'lecturer_count\': len(lecturer_ids),\n            \'teaching_days\': len(teaching_days),\n            \'merged_section_count\': len(merged_section_ids),\n        },\n    }\n\n\ndef weekly_workload_for_offerings(offerings):\n    """Return recurring weekly timetable rows for an already-scoped offering list."""\n    offering_ids = [offering.pk for offering in offerings]\n    if not offering_ids:\n        return _weekly_payload([])\n    schedules = list(\n        WeeklySchedule.objects.filter(class_subject_id__in=offering_ids)\n        .select_related(\n            \'class_subject__subject\',\n            \'class_subject__lecturer\',\n            \'class_subject__class_group__programme\',\n        )\n        .prefetch_related(\'class_subject__class_groups__programme\')\n        .order_by(\'weekday\', \'lecture_number\', \'class_subject__subject__name\')\n    )\n    return _weekly_payload(schedules)\n\n\ndef weekly_workload_for_lecturer(user):\n    """Return the active-term recurring weekly workload assigned to one lecturer."""\n    active_term = AcademicTerm.objects.filter(is_active=True).first()\n    if not active_term:\n        payload = _weekly_payload([])\n        payload[\'active_term\'] = None\n        return payload\n\n    schedules = list(\n        WeeklySchedule.objects.filter(class_subject__lecturer=user)\n        .filter(\n            Q(class_subject__class_groups__term=active_term)\n            | Q(\n                class_subject__class_group__term=active_term,\n                class_subject__class_groups__isnull=True,\n            )\n        )\n        .select_related(\n            \'class_subject__subject\',\n            \'class_subject__lecturer\',\n            \'class_subject__class_group__programme\',\n        )\n        .prefetch_related(\'class_subject__class_groups__programme\')\n        .distinct()\n        .order_by(\'weekday\', \'lecture_number\', \'class_subject__subject__name\')\n    )\n    payload = _weekly_payload(schedules)\n    payload[\'active_term\'] = active_term\n    return payload\n',
    'templates/lecturer/profile.html': '{% extends \'base.html\' %}\n{% block title %}My Profile | {{ app_branding.app_name }}{% endblock %}\n{% block crumb %}My Profile{% endblock %}\n{% block content %}\n<div class="page-heading student-page-heading">\n  <span class="eyebrow">LECTURER PORTAL</span>\n  <h1>My Profile</h1>\n  <p>Account details and regular weekly teaching workload for the active academic term.</p>\n</div>\n\n<div class="student-profile-layout">\n  <section class="panel student-profile-card">\n    <div class="student-profile-head">\n      <div class="student-profile-avatar">{{ user.username|slice:\':1\'|upper }}</div>\n      <div><small>Lecturer account</small><h2>{{ user.get_full_name|default:user.username }}</h2><span>{{ user.username }}</span></div>\n    </div>\n    <div class="student-profile-fields">\n      <div><span>Lecturer name</span><strong>{{ user.get_full_name|default:\'—\' }}</strong></div>\n      <div><span>Teacher ID</span><strong>{{ user.username }}</strong></div>\n      <div><span>Academic term</span><strong>{% if weekly.active_term %}{{ weekly.active_term.name }}{% else %}—{% endif %}</strong></div>\n      <div><span>Assigned subjects</span><strong>{{ weekly.summary.subject_count }}</strong></div>\n      <div><span>Subject sections</span><strong>{{ weekly.summary.section_count }}</strong></div>\n      <div><span>Linked classes</span><strong>{{ weekly.summary.class_count }}</strong></div>\n    </div>\n  </section>\n\n  <aside class="panel student-account-card">\n    <span class="eyebrow">ACCOUNT SECURITY</span>\n    <h2>Password</h2>\n    <p>You can change your login password. Teaching assignments and timetable changes remain administrator-controlled.</p>\n    <a class="btn btn-primary" href="{% url \'password_change\' %}">Change password</a>\n  </aside>\n</div>\n\n<section class="profile-workload-section">\n  <div class="section-heading">\n    <div><h2>Weekly workload</h2><p>Regular recurring timetable only. One merged-section timetable slot counts as one teaching lecture.</p></div>\n  </div>\n  <div class="metric-grid workload-metrics">\n    <article class="metric-card"><span>Weekly lectures</span><strong>{{ weekly.summary.lecture_count }}</strong></article>\n    <article class="metric-card"><span>Teaching days</span><strong>{{ weekly.summary.teaching_days }}</strong></article>\n    <article class="metric-card"><span>Subjects</span><strong>{{ weekly.summary.subject_count }}</strong></article>\n    <article class="metric-card"><span>Merged sections</span><strong>{{ weekly.summary.merged_section_count }}</strong></article>\n  </div>\n\n  <div class="weekly-workload-grid">\n    {% for day in weekly.days %}\n    <article class="panel workload-day-card">\n      <div class="workload-day-head"><h3>{{ day.label }}</h3><span class="count-badge">{{ day.lectures|length }}</span></div>\n      <div class="workload-day-list">\n        {% for item in day.lectures %}\n        <div class="workload-lecture-row">\n          <span class="workload-lecture-no">L{{ item.lecture_number }}</span>\n          <div><strong>{{ item.subject.name }}</strong><small>{{ item.subject.code }} · {{ item.class_codes }}{% if item.merged %} · Merged ({{ item.class_count }} classes){% endif %}</small></div>\n        </div>\n        {% empty %}<div class="workload-empty">No regular lectures.</div>{% endfor %}\n      </div>\n    </article>\n    {% endfor %}\n  </div>\n</section>\n{% endblock %}\n',
    'static/css/profile_workload.css': '/* Weekly timetable/workload cards shared by lecturer and student profiles. */\n.profile-workload-section{margin-top:24px}\n.workload-metrics{grid-template-columns:repeat(4,minmax(0,1fr));margin-bottom:16px}\n.weekly-workload-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;align-items:start}\n.workload-day-card{min-width:0;overflow:hidden;padding:0}\n.workload-day-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:14px 16px;border-bottom:1px solid var(--line);background:#fbfcfe}\n.workload-day-head h3{margin:0;font-size:13px;color:var(--ink)}\n.workload-day-list{display:grid}\n.workload-lecture-row{display:flex;align-items:flex-start;gap:11px;padding:13px 15px;border-top:1px solid #eef1f5;min-width:0}\n.workload-lecture-row:first-child{border-top:0}\n.workload-lecture-row>div{min-width:0;flex:1}\n.workload-lecture-row strong,.workload-lecture-row small{display:block;overflow-wrap:anywhere}\n.workload-lecture-row strong{font-size:11px;color:var(--ink)}\n.workload-lecture-row small{margin-top:3px;font-size:9px;line-height:1.45;color:var(--muted)}\n.workload-lecture-no{width:36px;height:36px;flex:0 0 36px;display:grid;place-items:center;border-radius:9px;background:#ebf2fc;color:var(--blue);font-size:11px;font-weight:850}\n.workload-empty{padding:18px 15px;color:var(--muted);font-size:10px;text-align:center}\n@media(max-width:1000px){.weekly-workload-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}\n@media(max-width:760px){.workload-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.weekly-workload-grid{grid-template-columns:1fr}}\n@media(max-width:380px){.workload-metrics{grid-template-columns:1fr}}\n',
    'templates/student/profile.html': '{% extends \'base.html\' %}\n{% block title %}My Profile | {{ app_branding.app_name }}{% endblock %}\n{% block crumb %}My Profile{% endblock %}\n{% block content %}\n<div class="page-heading student-page-heading">\n  <span class="eyebrow">STUDENT PORTAL</span>\n  <h1>My Profile</h1>\n  <p>Academic enrollment details and regular weekly timetable are read-only.</p>\n</div>\n\n<div class="student-profile-layout">\n  <section class="panel student-profile-card">\n    <div class="student-profile-head">\n      <div class="student-profile-avatar">{{ user.username|slice:\':1\'|upper }}</div>\n      <div><small>Student account</small><h2>{{ user.get_full_name|default:user.username }}</h2><span>{{ user.username }}</span></div>\n    </div>\n    <div class="student-profile-fields">\n      <div><span>Student name</span><strong>{{ user.get_full_name|default:\'—\' }}</strong></div>\n      <div><span>Registration number</span><strong>{{ user.username }}</strong></div>\n      <div><span>Programme</span><strong>{% if membership %}{{ membership.class_group.programme.name }}{% else %}—{% endif %}</strong>{% if membership %}<small>{{ membership.class_group.programme.code }}</small>{% endif %}</div>\n      <div><span>Class</span><strong>{% if membership %}{{ membership.class_group.name }}{% else %}—{% endif %}</strong>{% if membership %}<small>{{ membership.class_group.code }}</small>{% endif %}</div>\n      <div><span>Academic term</span><strong>{% if membership %}{{ membership.term.name }}{% else %}—{% endif %}</strong></div>\n      <div><span>Assigned subjects</span><strong>{{ assigned_subject_count }}</strong></div>\n    </div>\n  </section>\n\n  <aside class="panel student-account-card">\n    <span class="eyebrow">ACCOUNT SECURITY</span>\n    <h2>Password</h2>\n    <p>You can change your login password. Academic enrollment information cannot be edited from the student portal.</p>\n    <a class="btn btn-primary" href="{% url \'password_change\' %}">Change password</a>\n  </aside>\n</div>\n\n<section class="profile-workload-section">\n  <div class="section-heading">\n    <div><h2>My weekly lectures</h2><p>Regular recurring timetable for your current class. One-off make-up classes remain on My Schedule.</p></div>\n  </div>\n  <div class="metric-grid workload-metrics">\n    <article class="metric-card"><span>Weekly lectures</span><strong>{{ weekly.summary.lecture_count }}</strong></article>\n    <article class="metric-card"><span>Lecture days</span><strong>{{ weekly.summary.teaching_days }}</strong></article>\n    <article class="metric-card"><span>Subjects</span><strong>{{ weekly.summary.subject_count }}</strong></article>\n    <article class="metric-card"><span>Lecturers</span><strong>{{ weekly.summary.lecturer_count }}</strong></article>\n  </div>\n\n  <div class="weekly-workload-grid">\n    {% for day in weekly.days %}\n    <article class="panel workload-day-card">\n      <div class="workload-day-head"><h3>{{ day.label }}</h3><span class="count-badge">{{ day.lectures|length }}</span></div>\n      <div class="workload-day-list">\n        {% for item in day.lectures %}\n        <div class="workload-lecture-row">\n          <span class="workload-lecture-no">L{{ item.lecture_number }}</span>\n          <div><strong>{{ item.subject.name }}</strong><small>{{ item.subject.code }}{% if item.lecturer %} · {{ item.lecturer.get_full_name|default:item.lecturer.username }}{% endif %}</small></div>\n        </div>\n        {% empty %}<div class="workload-empty">No regular lectures.</div>{% endfor %}\n      </div>\n    </article>\n    {% endfor %}\n  </div>\n</section>\n{% endblock %}\n',
}

EXPECTED_FULL_OLD = {
    'templates/student/profile.html': '{% extends \'base.html\' %}\n{% block title %}My Profile | {{ app_branding.app_name }}{% endblock %}\n{% block crumb %}My Profile{% endblock %}\n{% block content %}\n<div class="page-heading student-page-heading">\n  <span class="eyebrow">STUDENT PORTAL</span>\n  <h1>My Profile</h1>\n  <p>Academic enrollment details are read-only.</p>\n</div>\n\n<div class="student-profile-layout">\n  <section class="panel student-profile-card">\n    <div class="student-profile-head">\n      <div class="student-profile-avatar">{{ user.username|slice:\':1\'|upper }}</div>\n      <div><small>Student account</small><h2>{{ user.get_full_name|default:user.username }}</h2><span>{{ user.username }}</span></div>\n    </div>\n    <div class="student-profile-fields">\n      <div><span>Student name</span><strong>{{ user.get_full_name|default:\'—\' }}</strong></div>\n      <div><span>Registration number</span><strong>{{ user.username }}</strong></div>\n      <div><span>Programme</span><strong>{% if membership %}{{ membership.class_group.programme.name }}{% else %}—{% endif %}</strong>{% if membership %}<small>{{ membership.class_group.programme.code }}</small>{% endif %}</div>\n      <div><span>Class</span><strong>{% if membership %}{{ membership.class_group.name }}{% else %}—{% endif %}</strong>{% if membership %}<small>{{ membership.class_group.code }}</small>{% endif %}</div>\n      <div><span>Academic term</span><strong>{% if membership %}{{ membership.term.name }}{% else %}—{% endif %}</strong></div>\n      <div><span>Assigned subjects</span><strong>{{ assigned_subject_count }}</strong></div>\n    </div>\n  </section>\n\n  <aside class="panel student-account-card">\n    <span class="eyebrow">ACCOUNT SECURITY</span>\n    <h2>Password</h2>\n    <p>You can change your login password. Academic enrollment information cannot be edited from the student portal.</p>\n    <a class="btn btn-primary" href="{% url \'password_change\' %}">Change password</a>\n  </aside>\n</div>\n{% endblock %}\n',
}


def fail(message):
    print(f"ERROR: {message}")
    sys.exit(1)


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def validate():
    if not (ROOT / 'manage.py').exists():
        fail('Run this script from the attendance_app directory containing manage.py.')

    problems = []
    plan = {}

    for path, pairs in REPLACEMENTS.items():
        target = ROOT / path
        if not target.exists():
            problems.append(f'{path} is missing.')
            continue
        content = target.read_text(encoding='utf-8')
        new_content = content
        changes = 0
        for old, new in pairs:
            if new in new_content:
                continue
            count = new_content.count(old)
            if count != 1:
                problems.append(
                    f'{path}: expected code anchor was found {count} times. '
                    'The file may differ from Clasvanta v2.8.5; nothing has been changed.'
                )
                continue
            new_content = new_content.replace(old, new, 1)
            changes += 1
        plan[path] = (content, new_content, changes)

    for path, payload in FULL_FILES.items():
        target = ROOT / path
        if path in EXPECTED_FULL_OLD and target.exists():
            current = target.read_text(encoding='utf-8')
            if current == payload:
                plan[path] = (current, current, 0)
            elif current == EXPECTED_FULL_OLD[path]:
                plan[path] = (current, payload, 1)
            else:
                problems.append(
                    f'{path} has local changes that this installer will not overwrite. '
                    'Nothing has been changed.'
                )
        elif target.exists():
            current = target.read_text(encoding='utf-8')
            if current == payload:
                plan[path] = (current, current, 0)
            else:
                problems.append(
                    f'{path} already exists with different content. '
                    'Nothing has been changed.'
                )
        else:
            plan[path] = (None, payload, 1)

    if problems:
        print('VALIDATION FAILED')
        for item in problems:
            print(' -', item)
        sys.exit(2)
    return plan


def install(plan):
    changed = [path for path, (_, new, changes) in plan.items() if changes]
    if not changed:
        print('Weekly profile/workload feature is already installed. No changes required.')
        return

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_root = ROOT / f'.weekly_profile_backup_{stamp}'
    backup_root.mkdir(parents=True, exist_ok=False)

    for path in changed:
        old, new, _ = plan[path]
        target = ROOT / path
        if old is not None and target.exists():
            backup = backup_root / path
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)

    try:
        for path in changed:
            _, new, _ = plan[path]
            target = ROOT / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new, encoding='utf-8', newline='')

        for path in ('academics/workload.py', 'academics/student_portal.py', 'attendance/views.py', 'config/urls.py'):
            py_compile.compile(str(ROOT / path), doraise=True)
    except Exception as exc:
        print('INSTALL FAILED. Restoring backups...')
        for path in changed:
            backup = backup_root / path
            target = ROOT / path
            if backup.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, target)
            elif target.exists() and plan[path][0] is None:
                target.unlink()
        fail(str(exc))

    print('SUCCESS: weekly profile/workload feature installed.')
    print('Backup directory:', backup_root.name)
    print('Changed/created files:')
    for path in changed:
        print(' -', path)
    print()
    print('NEXT COMMANDS:')
    print('  source .venv/bin/activate')
    print('  python manage.py check')
    print('  python manage.py collectstatic --noinput')
    print('Then restart the Python application in Plesk.')
    print('No database migration is required.')


if __name__ == '__main__':
    install(validate())
