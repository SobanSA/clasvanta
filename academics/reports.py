"""Administrator reporting for Clasvanta v2.8.1.

Reports deliberately derive state from the existing timetable and attendance
models. A recurring/approved occurrence is scheduled; only a SUBMITTED
LectureSession is Held. CANCELLED sessions remain visible and an occurrence
without a session is Pending/Not marked once its date has arrived.
"""
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO

from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET

from accounts.models import User
from accounts.views import role_required
from attendance.models import AttendanceRecord, LectureSession, MakeupClass
from fines.models import FineLedgerEntry, FinePolicy

from .branding import get_app_branding
from .models import (
    AcademicTerm,
    ClassGroup,
    ClassMembership,
    ClassSubject,
    Programme,
    StudentProfile,
    Subject,
    WeeklySchedule,
)

REPORT_TYPES = [
    ('compliance', 'Schedule compliance'),
    ('monthly_lecturer', 'Monthly missing & make-up lectures'),
    ('timetable_compliance', 'Lec in timetable compliance'),
    ('daily', 'Daily attendance'),
    ('class', 'Class attendance'),
    ('student', 'Student attendance history'),
    ('defaulters', 'Absence defaulters'),
    ('fines', 'Fine ledger'),
]


def _int_param(request, name):
    raw = request.GET.get(name, '').strip()
    return int(raw) if raw.isdigit() else None


def _month_bounds(raw):
    today = timezone.localdate()
    try:
        selected = datetime.strptime(raw or '', '%Y-%m').date().replace(day=1)
    except ValueError:
        selected = today.replace(day=1)
    current_month = today.replace(day=1)
    # Compliance is a to-date measure. Do not turn future timetable rows into
    # artificial Pending classes.
    if selected > current_month:
        selected = current_month
    month_end = selected.replace(day=monthrange(selected.year, selected.month)[1])
    report_end = min(month_end, today)
    return selected, month_end, report_end


def _parse_date(raw, fallback):
    try:
        return date.fromisoformat(raw) if raw else fallback
    except ValueError:
        return fallback


def _linked_classes(offering):
    groups = list(offering.class_groups.all())
    return groups or ([offering.class_group] if offering.class_group_id else [])


def _filter_models(request, month_start, report_end):
    programme_id = _int_param(request, 'programme')
    class_id = _int_param(request, 'class')
    subject_id = _int_param(request, 'subject')
    lecturer_id = _int_param(request, 'lecturer')

    programmes = Programme.objects.all().order_by('code')
    classes = ClassGroup.objects.filter(
        term__start_date__lte=report_end,
        term__end_date__gte=month_start,
    ).select_related('programme', 'term').order_by('programme__code', 'semester_number', 'code')
    if programme_id:
        classes = classes.filter(programme_id=programme_id)

    selected_programme = programmes.filter(pk=programme_id).first() if programme_id else None
    selected_class = classes.filter(pk=class_id).first() if class_id else None
    subjects = Subject.objects.all().order_by('name', 'code')
    selected_subject = subjects.filter(pk=subject_id).first() if subject_id else None
    lecturers = User.objects.filter(role=User.Role.LECTURER).order_by('first_name', 'last_name', 'username')
    selected_lecturer = lecturers.filter(pk=lecturer_id).first() if lecturer_id else None

    return {
        'programme_id': programme_id,
        'class_id': selected_class.pk if selected_class else None,
        'subject_id': subject_id,
        'lecturer_id': lecturer_id,
        'programmes': programmes,
        'classes': classes,
        'subjects': subjects,
        'lecturers': lecturers,
        'selected_programme': selected_programme,
        'selected_class': selected_class,
        'selected_subject': selected_subject,
        'selected_lecturer': selected_lecturer,
    }



def _filtered_student_ids(filters, start_date, end_date):
    # Return student ids constrained by class/programme filters, or None for all.
    if not filters.get('class_id') and not filters.get('programme_id'):
        return None
    memberships = ClassMembership.objects.filter(
        term__start_date__lte=end_date,
        term__end_date__gte=start_date,
    )
    if filters.get('class_id'):
        memberships = memberships.filter(class_group_id=filters['class_id'])
    elif filters.get('programme_id'):
        memberships = memberships.filter(class_group__programme_id=filters['programme_id'])
    return set(memberships.values_list('student_id', flat=True))

def _offering_queryset(month_start, report_end, filters):
    overlap = (
        Q(class_groups__term__start_date__lte=report_end, class_groups__term__end_date__gte=month_start) |
        Q(
            class_group__term__start_date__lte=report_end,
            class_group__term__end_date__gte=month_start,
            class_groups__isnull=True,
        )
    )
    qs = ClassSubject.objects.filter(overlap)
    if filters['programme_id']:
        qs = qs.filter(
            Q(class_groups__programme_id=filters['programme_id']) |
            Q(class_group__programme_id=filters['programme_id'], class_groups__isnull=True)
        )
    if filters['class_id']:
        qs = qs.filter(
            Q(class_groups__id=filters['class_id']) |
            Q(class_group_id=filters['class_id'], class_groups__isnull=True)
        )
    if filters['subject_id']:
        qs = qs.filter(subject_id=filters['subject_id'])
    if filters['lecturer_id']:
        qs = qs.filter(lecturer_id=filters['lecturer_id'])
    return qs.select_related(
        'subject', 'lecturer', 'class_group__term', 'class_group__programme'
    ).prefetch_related(
        'class_groups__programme', 'class_groups__term'
    ).distinct().order_by('subject__name', 'class_group__code')


def _first_weekday(start, weekday):
    return start + timedelta(days=(weekday - start.weekday()) % 7)


def _occurrences(offerings, start_date, end_date):
    """Build expected regular + approved make-up occurrences for a range."""
    offerings = list(offerings)
    if not offerings or end_date < start_date:
        return []
    offering_map = {item.pk: item for item in offerings}
    ids = list(offering_map)
    schedules = WeeklySchedule.objects.filter(class_subject_id__in=ids).select_related('class_subject')
    sessions = {
        (item.class_subject_id, item.lecture_date, item.lecture_number): item
        for item in LectureSession.objects.filter(
            class_subject_id__in=ids,
            lecture_date__range=(start_date, end_date),
        ).select_related('submitted_by')
    }
    makeups = list(MakeupClass.objects.filter(
        class_subject_id__in=ids,
        lecture_date__range=(start_date, end_date),
        status=MakeupClass.APPROVED,
    ).select_related('class_subject'))

    today = timezone.localdate()
    rows = []
    seen = set()

    def add(offering, lecture_date, lecture_number, source, makeup=None):
        key = (offering.pk, lecture_date, lecture_number)
        if key in seen:
            return
        seen.add(key)
        session = sessions.get(key)
        if session and session.status == 'SUBMITTED':
            state, label = 'HELD', 'Held'
        elif session and session.status == 'CANCELLED':
            state, label = 'CANCELLED', 'Cancelled'
        elif lecture_date > today:
            state, label = 'SCHEDULED', 'Scheduled'
        else:
            state, label = 'PENDING', 'Not marked'
        rows.append({
            'offering': offering,
            'date': lecture_date,
            'lecture_number': lecture_number,
            'source': source,
            'makeup': makeup,
            'session': session,
            'state': state,
            'state_label': label,
            'classes': _linked_classes(offering),
        })

    for schedule in schedules:
        offering = offering_map.get(schedule.class_subject_id)
        if not offering:
            continue
        term = offering.term
        if not term:
            continue
        begin = max(start_date, term.start_date)
        finish = min(end_date, term.end_date)
        if begin > finish:
            continue
        day = _first_weekday(begin, schedule.weekday)
        while day <= finish:
            add(offering, day, schedule.lecture_number, 'REGULAR')
            day += timedelta(days=7)

    for makeup in makeups:
        offering = offering_map.get(makeup.class_subject_id)
        if offering:
            add(offering, makeup.lecture_date, makeup.lecture_number, 'MAKEUP', makeup=makeup)

    rows.sort(key=lambda row: (row['date'], row['lecture_number'], row['offering'].subject.name.lower()))
    return rows


def _percent(numerator, denominator):
    return round((numerator * 100.0) / denominator, 1) if denominator else 0.0


def _summary_occurrences(rows):
    expected = [row for row in rows if row['source'] in {'REGULAR', 'MAKEUP'}]
    return {
        'scheduled': len(expected),
        'held': sum(row['state'] == 'HELD' for row in expected),
        'cancelled': sum(row['state'] == 'CANCELLED' for row in expected),
        'pending': sum(row['state'] == 'PENDING' for row in expected),
        'upcoming': sum(row['state'] == 'SCHEDULED' for row in expected),
        'makeup': sum(row['source'] == 'MAKEUP' for row in expected),
        'completion': _percent(sum(row['state'] == 'HELD' for row in expected), len(expected)),
    }


def _class_aggregate(rows, filters):
    selected_class_id = filters['class_id']
    selected_programme_id = filters['programme_id']
    data = {}
    for row in rows:
        for group in row['classes']:
            if selected_class_id and group.pk != selected_class_id:
                continue
            if selected_programme_id and group.programme_id != selected_programme_id:
                continue
            bucket = data.setdefault(group.pk, {
                'class_group': group, 'scheduled': 0, 'held': 0, 'cancelled': 0,
                'pending': 0, 'makeup': 0,
            })
            bucket['scheduled'] += 1
            bucket['held'] += row['state'] == 'HELD'
            bucket['cancelled'] += row['state'] == 'CANCELLED'
            bucket['pending'] += row['state'] == 'PENDING'
            bucket['makeup'] += row['source'] == 'MAKEUP'
    result = list(data.values())
    for item in result:
        item['completion'] = _percent(item['held'], item['scheduled'])
    result.sort(key=lambda item: (item['class_group'].programme.code, item['class_group'].semester_number, item['class_group'].code))
    return result


def _teacher_aggregate(rows):
    data = {}
    for row in rows:
        lecturer = row['offering'].lecturer
        key = lecturer.pk if lecturer else 0
        bucket = data.setdefault(key, {
            'lecturer': lecturer, 'scheduled': 0, 'held': 0, 'cancelled': 0,
            'pending': 0, 'makeup': 0,
        })
        bucket['scheduled'] += 1
        bucket['held'] += row['state'] == 'HELD'
        bucket['cancelled'] += row['state'] == 'CANCELLED'
        bucket['pending'] += row['state'] == 'PENDING'
        bucket['makeup'] += row['source'] == 'MAKEUP'
    result = list(data.values())
    for item in result:
        item['completion'] = _percent(item['held'], item['scheduled'])
    result.sort(key=lambda item: (
        1 if item['lecturer'] is None else 0,
        (item['lecturer'].get_full_name() or item['lecturer'].username).lower() if item['lecturer'] else 'zzzz',
    ))
    return result


def _compliance_report(offerings, month_start, report_end, filters):
    rows = _occurrences(offerings, month_start, report_end)
    return {
        'rows': rows,
        'summary': _summary_occurrences(rows),
        'class_rows': _class_aggregate(rows, filters),
        'teacher_rows': _teacher_aggregate(rows),
    }


def _monthly_lecturer_report(offerings, month_start, report_end, filters):
    """Spreadsheet-style monthly teacher/class lecture register.

    ``lec_in_timetable`` is the number of recurring WeeklySchedule slots assigned
    to the lecturer for that linked class within the currently filtered offering
    scope. Approved make-up lectures do not inflate that recurring timetable
    count. Each merged teaching occurrence is expanded once per linked class so
    the report remains class-specific like the administrative sheet it replaces.
    """
    offerings = list(offerings)
    occurrence_rows = _occurrences(offerings, month_start, report_end)
    offering_map = {item.pk: item for item in offerings}

    selected_class_id = filters.get('class_id')
    selected_programme_id = filters.get('programme_id')

    def visible_groups(offering):
        groups = _linked_classes(offering)
        if selected_class_id:
            groups = [group for group in groups if group.pk == selected_class_id]
        if selected_programme_id:
            groups = [group for group in groups if group.programme_id == selected_programme_id]
        return groups

    timetable_counts = defaultdict(int)
    if offering_map:
        schedules = WeeklySchedule.objects.filter(
            class_subject_id__in=offering_map.keys(),
        ).select_related('class_subject__lecturer')
        for schedule in schedules:
            offering = offering_map.get(schedule.class_subject_id)
            if not offering:
                continue
            lecturer_id = offering.lecturer_id or 0
            for group in visible_groups(offering):
                timetable_counts[(lecturer_id, group.pk)] += 1

    rows = []
    for occurrence in occurrence_rows:
        offering = occurrence['offering']

        # This register intentionally excludes cancellation and future-schedule
        # analysis. Those rows belong in the separate compliance/daily reports.
        if occurrence['source'] == 'MAKEUP':
            # A cancelled make-up is a cancellation event, not a make-up row
            # for this report. Approved make-ups that are Held or still unmarked
            # are both represented as "Make-up Lecture".
            if occurrence['state'] == 'CANCELLED':
                continue
            status = 'Make-up Lecture'
        elif occurrence['state'] == 'HELD':
            status = 'Held Lecture'
        elif occurrence['state'] == 'PENDING':
            status = 'Missing Lecture'
        else:
            # Future regular scheduled rows are intentionally omitted.
            continue

        lecturer_id = offering.lecturer_id or 0
        for group in visible_groups(offering):
            rows.append({
                'lecturer': offering.lecturer,
                'class_group': group,
                'lec_in_timetable': timetable_counts.get((lecturer_id, group.pk), 0),
                'date': occurrence['date'],
                'day': occurrence['date'].strftime('%A'),
                'status': status,
                'remarks': '',
                'source': occurrence['source'],
                'state': occurrence['state'],
                'offering': offering,
            })

    rows.sort(key=lambda item: (
        item['date'],
        (item['lecturer'].get_full_name() or item['lecturer'].username).lower() if item['lecturer'] else 'zzzz',
        item['class_group'].code,
        item['offering'].subject.name.lower(),
    ))
    return {
        'rows': rows,
        'summary': {
            'rows': len(rows),
            'teachers': len({row['lecturer'].pk for row in rows if row['lecturer']}),
            'classes': len({row['class_group'].pk for row in rows}),
            'held': sum(row['status'] == 'Held Lecture' for row in rows),
            'missing': sum(row['status'] == 'Missing Lecture' for row in rows),
            'makeup': sum(row['status'] == 'Make-up Lecture' for row in rows),
        },
    }


def _timetable_compliance_report(offerings, month_start, report_end, filters):
    """Compare regular timetable delivery with missing and Held make-up lectures.

    Cancelled regular occurrences are intentionally outside this report. Future
    scheduled occurrences are also excluded by the month-to-date reporting range.
    A Held make-up can compensate for a missing regular occurrence in the
    compliance percentage, capped at 100%.
    """
    offerings = list(offerings)
    occurrences = _occurrences(offerings, month_start, report_end)
    selected_class_id = filters.get('class_id')
    selected_programme_id = filters.get('programme_id')

    schedule_counts = dict(
        WeeklySchedule.objects.filter(class_subject_id__in=[item.pk for item in offerings])
        .values('class_subject_id')
        .annotate(total=Count('id'))
        .values_list('class_subject_id', 'total')
    )

    def visible_groups(offering):
        groups = _linked_classes(offering)
        if selected_class_id:
            groups = [group for group in groups if group.pk == selected_class_id]
        if selected_programme_id:
            groups = [group for group in groups if group.programme_id == selected_programme_id]
        return groups

    buckets = {}
    for offering in offerings:
        for group in visible_groups(offering):
            key = (offering.pk, group.pk)
            buckets[key] = {
                'offering': offering,
                'lecturer': offering.lecturer,
                'class_group': group,
                'lec_in_timetable': schedule_counts.get(offering.pk, 0),
                'expected': 0,
                'held': 0,
                'missing': 0,
                'makeup_held': 0,
            }

    for occurrence in occurrences:
        offering = occurrence['offering']
        for group in visible_groups(offering):
            bucket = buckets.get((offering.pk, group.pk))
            if not bucket:
                continue
            if occurrence['source'] == 'REGULAR':
                # Cancelled belongs to the separate schedule-compliance report.
                if occurrence['state'] == 'HELD':
                    bucket['expected'] += 1
                    bucket['held'] += 1
                elif occurrence['state'] == 'PENDING':
                    bucket['expected'] += 1
                    bucket['missing'] += 1
            elif occurrence['source'] == 'MAKEUP' and occurrence['state'] == 'HELD':
                bucket['makeup_held'] += 1

    rows = []
    for bucket in buckets.values():
        if not (bucket['expected'] or bucket['makeup_held']):
            continue
        bucket['delivered'] = bucket['held'] + bucket['makeup_held']
        raw_compliance = _percent(bucket['delivered'], bucket['expected']) if bucket['expected'] else 0.0
        bucket['compliance'] = min(100.0, raw_compliance)
        rows.append(bucket)

    rows.sort(key=lambda item: (
        1 if item['lecturer'] is None else 0,
        (item['lecturer'].get_full_name() or item['lecturer'].username).lower() if item['lecturer'] else 'zzzz',
        item['class_group'].code,
        item['offering'].subject.name.lower(),
    ))

    expected = sum(item['expected'] for item in rows)
    held = sum(item['held'] for item in rows)
    missing = sum(item['missing'] for item in rows)
    makeup_held = sum(item['makeup_held'] for item in rows)
    delivered = held + makeup_held
    return {
        'rows': rows,
        'summary': {
            'rows': len(rows),
            'expected': expected,
            'held': held,
            'missing': missing,
            'makeup_held': makeup_held,
            'delivered': delivered,
            'compliance': min(100.0, _percent(delivered, expected)) if expected else 0.0,
        },
    }


def _daily_report(offerings, selected_date, student_ids=None):
    rows = _occurrences(offerings, selected_date, selected_date)
    expected_keys = {(row['offering'].pk, row['date'], row['lecture_number']) for row in rows}
    ids = [item.pk for item in offerings]
    # Preserve visibility of manually-created historical sessions even if they do
    # not correspond to today's current recurring timetable or an approved make-up.
    if ids:
        extras = LectureSession.objects.filter(
            class_subject_id__in=ids, lecture_date=selected_date,
        ).select_related('class_subject__subject', 'class_subject__lecturer', 'submitted_by').prefetch_related(
            'class_subject__class_groups__programme'
        )
        for session in extras:
            key = (session.class_subject_id, session.lecture_date, session.lecture_number)
            if key in expected_keys:
                continue
            offering = session.class_subject
            rows.append({
                'offering': offering,
                'date': selected_date,
                'lecture_number': session.lecture_number,
                'source': 'ADDITIONAL',
                'makeup': None,
                'session': session,
                'state': 'HELD' if session.status == 'SUBMITTED' else 'CANCELLED',
                'state_label': 'Held' if session.status == 'SUBMITTED' else 'Cancelled',
                'classes': _linked_classes(offering),
            })

    held_session_ids = [row['session'].pk for row in rows if row.get('session') and row['state'] == 'HELD']
    counts = {}
    if held_session_ids:
        record_scope = AttendanceRecord.objects.filter(session_id__in=held_session_ids)
        if student_ids is not None:
            record_scope = record_scope.filter(student_id__in=student_ids)
        for item in record_scope.values('session_id').annotate(
            present=Count('id', filter=Q(status=AttendanceRecord.PRESENT)),
            absent=Count('id', filter=Q(status=AttendanceRecord.ABSENT)),
        ):
            counts[item['session_id']] = item
    for row in rows:
        attendance = counts.get(row['session'].pk if row.get('session') else None, {})
        row['present'] = attendance.get('present', 0)
        row['absent'] = attendance.get('absent', 0)
        row['marked'] = row['present'] + row['absent']

    rows.sort(key=lambda row: (row['lecture_number'], row['offering'].subject.name.lower(), row['source']))
    summary = _summary_occurrences(rows)
    summary['additional'] = sum(row['source'] == 'ADDITIONAL' for row in rows)
    summary['held_all'] = sum(row['state'] == 'HELD' for row in rows)
    summary['cancelled_all'] = sum(row['state'] == 'CANCELLED' for row in rows)
    return {'rows': rows, 'summary': summary, 'selected_date': selected_date}


def _class_report(offerings, selected_class, month_start, report_end):
    if not selected_class:
        return {'subject_rows': [], 'student_rows': [], 'summary': {}, 'selected_class': None}
    offerings = [item for item in offerings if selected_class.pk in [group.pk for group in _linked_classes(item)]]
    offering_ids = [item.pk for item in offerings]
    occurrences = _occurrences(offerings, month_start, report_end)
    occurrence_by_offering = defaultdict(list)
    for row in occurrences:
        occurrence_by_offering[row['offering'].pk].append(row)

    memberships = list(ClassMembership.objects.filter(
        class_group=selected_class,
        term=selected_class.term,
    ).select_related('student__user').order_by('student__user__username'))
    student_ids = [item.student_id for item in memberships]
    records_by_offering = defaultdict(list)
    records_by_student = defaultdict(list)
    if offering_ids and student_ids:
        records = AttendanceRecord.objects.filter(
            student_id__in=student_ids,
            session__class_subject_id__in=offering_ids,
            session__status='SUBMITTED',
            session__lecture_date__range=(month_start, report_end),
        ).select_related('session', 'student__user')
        for record in records:
            records_by_offering[record.session.class_subject_id].append(record)
            records_by_student[record.student_id].append(record)

    subject_rows = []
    for offering in offerings:
        occ = occurrence_by_offering.get(offering.pk, [])
        records = records_by_offering.get(offering.pk, [])
        present = sum(item.status == AttendanceRecord.PRESENT for item in records)
        absent = sum(item.status == AttendanceRecord.ABSENT for item in records)
        subject_rows.append({
            'offering': offering,
            'scheduled': len(occ),
            'held': sum(item['state'] == 'HELD' for item in occ),
            'cancelled': sum(item['state'] == 'CANCELLED' for item in occ),
            'pending': sum(item['state'] == 'PENDING' for item in occ),
            'makeup': sum(item['source'] == 'MAKEUP' for item in occ),
            'present': present,
            'absent': absent,
            'marks': present + absent,
            'attendance_rate': _percent(present, present + absent),
        })

    student_rows = []
    for membership in memberships:
        records = records_by_student.get(membership.student_id, [])
        present = sum(item.status == AttendanceRecord.PRESENT for item in records)
        absent = sum(item.status == AttendanceRecord.ABSENT for item in records)
        student_rows.append({
            'student': membership.student,
            'present': present,
            'absent': absent,
            'held_marks': present + absent,
            'attendance_rate': _percent(present, present + absent),
        })

    overall_present = sum(item['present'] for item in student_rows)
    overall_absent = sum(item['absent'] for item in student_rows)
    compliance = _summary_occurrences(occurrences)
    return {
        'subject_rows': subject_rows,
        'student_rows': student_rows,
        'selected_class': selected_class,
        'summary': {
            **compliance,
            'students': len(student_rows),
            'present_marks': overall_present,
            'absent_marks': overall_absent,
            'attendance_rate': _percent(overall_present, overall_present + overall_absent),
        },
    }


def _student_search(request, month_start, report_end, filters):
    selected_id = _int_param(request, 'student')
    query = request.GET.get('student_q', '').strip()
    memberships = ClassMembership.objects.filter(
        term__start_date__lte=report_end,
        term__end_date__gte=month_start,
    ).select_related('student__user', 'class_group__programme', 'term')
    if filters['programme_id']:
        memberships = memberships.filter(class_group__programme_id=filters['programme_id'])
    if filters['class_id']:
        memberships = memberships.filter(class_group_id=filters['class_id'])
    selected_membership = memberships.filter(student_id=selected_id).order_by('-term__start_date').first() if selected_id else None
    search_results = []
    if query and not selected_membership:
        search_results = list(memberships.filter(
            Q(student__user__username__icontains=query) |
            Q(student__user__first_name__icontains=query) |
            Q(student__user__last_name__icontains=query)
        ).order_by('student__user__username')[:25])
    return selected_membership, search_results, query


def _student_report(request, offerings, month_start, report_end, filters):
    membership, search_results, query = _student_search(request, month_start, report_end, filters)
    if not membership:
        return {
            'membership': None, 'student': None, 'search_results': search_results,
            'student_q': query, 'history': [], 'summary': {},
        }
    student = membership.student
    group = membership.class_group
    allowed_ids = {
        item.pk for item in offerings
        if group.pk in [linked.pk for linked in _linked_classes(item)]
    }
    records = AttendanceRecord.objects.filter(
        student=student,
        session__status='SUBMITTED',
        session__lecture_date__range=(month_start, report_end),
    ).select_related(
        'session__class_subject__subject', 'session__class_subject__lecturer', 'session__submitted_by'
    ).order_by('-session__lecture_date', '-session__lecture_number')
    if allowed_ids:
        records = records.filter(session__class_subject_id__in=allowed_ids)
    else:
        records = records.none()
    makeup_keys = set(MakeupClass.objects.filter(
        class_subject_id__in=allowed_ids,
        status=MakeupClass.APPROVED,
        lecture_date__range=(month_start, report_end),
    ).values_list('class_subject_id', 'lecture_date', 'lecture_number')) if allowed_ids else set()
    regular_slots = defaultdict(set)
    if allowed_ids:
        for schedule in WeeklySchedule.objects.filter(class_subject_id__in=allowed_ids):
            regular_slots[schedule.class_subject_id].add((schedule.weekday, schedule.lecture_number))

    history = []
    present = absent = 0
    for record in records:
        session = record.session
        present += record.status == AttendanceRecord.PRESENT
        absent += record.status == AttendanceRecord.ABSENT
        key = (session.class_subject_id, session.lecture_date, session.lecture_number)
        if key in makeup_keys:
            source = 'Make-up'
        elif (session.lecture_date.weekday(), session.lecture_number) in regular_slots.get(session.class_subject_id, set()):
            source = 'Regular'
        else:
            source = 'Additional'
        history.append({
            'record': record,
            'session': session,
            'offering': session.class_subject,
            'source': source,
        })
    return {
        'membership': membership,
        'student': student,
        'search_results': [],
        'student_q': query,
        'history': history,
        'summary': {
            'present': present,
            'absent': absent,
            'held': present + absent,
            'attendance_rate': _percent(present, present + absent),
        },
    }


def _defaulters_report(offerings, month_start, report_end, student_ids=None):
    offerings = list(offerings)
    offering_ids = [item.pk for item in offerings]
    if not offering_ids:
        return {'rows': [], 'summary': {'students': 0, 'subjects': 0, 'rows': 0}}
    offering_map = {item.pk: item for item in offerings}
    policies = {
        policy.term_id: policy
        for policy in FinePolicy.objects.filter(term_id__in={item.term.pk for item in offerings if item.term})
    }

    # Monthly marks are shown for context, but the defaulter decision is cumulative
    # from term start through the selected report end because the absence allowance
    # is a term policy, not a per-month allowance.
    month_scope = AttendanceRecord.objects.filter(
        session__class_subject_id__in=offering_ids,
        session__status='SUBMITTED',
        session__lecture_date__range=(month_start, report_end),
    )
    if student_ids is not None:
        month_scope = month_scope.filter(student_id__in=student_ids)
    month_stats = {
        (item['student_id'], item['session__class_subject_id']): item
        for item in month_scope.values('student_id', 'session__class_subject_id').annotate(
            present=Count('id', filter=Q(status=AttendanceRecord.PRESENT)),
            absent=Count('id', filter=Q(status=AttendanceRecord.ABSENT)),
            held=Count('id'),
        )
    }

    term_bounds_by_offering = {
        item.pk: (item.term.start_date, min(item.term.end_date, report_end))
        for item in offerings if item.term
    }
    rows = []
    ledger_scope = FineLedgerEntry.objects.filter(class_subject_id__in=offering_ids)
    if student_ids is not None:
        ledger_scope = ledger_scope.filter(student_id__in=student_ids)
    balance_map = {
        (item['student_id'], item['class_subject_id']): item['balance'] or Decimal('0.00')
        for item in ledger_scope.values('student_id', 'class_subject_id').annotate(balance=Sum('amount'))
    }

    # One query per distinct term-start group keeps the logic correct for historical
    # terms while avoiding an unsafe assumption that every selected section shares a term.
    grouped_ids = defaultdict(list)
    for offering_id, term_bounds in term_bounds_by_offering.items():
        grouped_ids[term_bounds].append(offering_id)
    cumulative = []
    for (term_start, term_end), ids in grouped_ids.items():
        cumulative_scope = AttendanceRecord.objects.filter(
            session__class_subject_id__in=ids,
            session__status='SUBMITTED',
            session__lecture_date__range=(term_start, term_end),
        )
        if student_ids is not None:
            cumulative_scope = cumulative_scope.filter(student_id__in=student_ids)
        cumulative.extend(cumulative_scope.values(
            'student_id', 'student__user__username', 'student__user__first_name', 'student__user__last_name',
            'session__class_subject_id',
        ).annotate(
            present=Count('id', filter=Q(status=AttendanceRecord.PRESENT)),
            absent=Count('id', filter=Q(status=AttendanceRecord.ABSENT)),
            held=Count('id'),
        ))

    for item in cumulative:
        offering = offering_map.get(item['session__class_subject_id'])
        if not offering or not offering.term:
            continue
        policy = policies.get(offering.term.pk)
        allowed = policy.allowed_absences if policy else FinePolicy._meta.get_field('allowed_absences').default
        if item['absent'] <= allowed:
            continue
        monthly = month_stats.get((item['student_id'], offering.pk), {'present': 0, 'absent': 0, 'held': 0})
        rows.append({
            'student_id': item['student_id'],
            'registration': item['student__user__username'],
            'student_name': (' '.join(filter(None, [item['student__user__first_name'], item['student__user__last_name']])) or item['student__user__username']),
            'offering': offering,
            'allowed': allowed,
            'term_absent': item['absent'],
            'term_present': item['present'],
            'term_held': item['held'],
            'excess': item['absent'] - allowed,
            'month_absent': monthly['absent'],
            'month_present': monthly['present'],
            'month_held': monthly['held'],
            'attendance_rate': _percent(item['present'], item['held']),
            'fine_balance': max(Decimal('0.00'), balance_map.get((item['student_id'], offering.pk), Decimal('0.00'))),
        })
    rows.sort(key=lambda item: (-item['excess'], item['registration'], item['offering'].subject.name.lower()))
    return {
        'rows': rows,
        'summary': {
            'students': len({item['student_id'] for item in rows}),
            'subjects': len({item['offering'].pk for item in rows}),
            'rows': len(rows),
        },
    }


def _fines_report(offerings, month_start, report_end, student_ids=None):
    offerings = list(offerings)
    ids = [item.pk for item in offerings]
    entry_scope = FineLedgerEntry.objects.filter(
        class_subject_id__in=ids,
        created_at__date__range=(month_start, report_end),
    )
    if student_ids is not None:
        entry_scope = entry_scope.filter(student_id__in=student_ids)
    entries = list(entry_scope.select_related(
        'student__user', 'class_subject__subject', 'class_subject__lecturer', 'actor'
    ).prefetch_related('class_subject__class_groups').order_by('-created_at', '-pk')) if ids else []

    charges = sum((item.amount for item in entries if item.kind == 'CHARGE'), Decimal('0.00'))
    adjustments = sum((item.amount for item in entries if item.kind == 'ADJUSTMENT'), Decimal('0.00'))
    payments = sum((item.amount for item in entries if item.kind == 'PAYMENT'), Decimal('0.00'))

    balances = []
    if ids:
        balance_scope = FineLedgerEntry.objects.filter(class_subject_id__in=ids)
        if student_ids is not None:
            balance_scope = balance_scope.filter(student_id__in=student_ids)
        raw = balance_scope.values(
            'student_id', 'student__user__username', 'student__user__first_name', 'student__user__last_name',
            'class_subject_id', 'class_subject__subject__name', 'class_subject__subject__code',
        ).annotate(balance=Sum('amount')).order_by('student__user__username', 'class_subject__subject__name')
        offering_map = {item.pk: item for item in offerings}
        for item in raw:
            if item['balance'] and item['balance'] > 0:
                item['offering'] = offering_map.get(item['class_subject_id'])
                balances.append(item)
    return {
        'entries': entries,
        'balances': balances,
        'summary': {
            'charges': charges,
            'adjustments': adjustments,
            'payments': abs(payments),
            'net': charges + adjustments + payments,
            'entry_count': len(entries),
            'outstanding_count': len(balances),
            'outstanding_total': sum((item['balance'] for item in balances), Decimal('0.00')),
        },
    }


def _sheet_title(ws, title, subtitle=None):
    ws.append([title])
    if subtitle:
        ws.append([subtitle])
    ws.append([])


def _append_table(ws, headers, rows):
    ws.append(headers)
    for row in rows:
        ws.append(row)
    ws.freeze_panes = f'A{ws.max_row - len(rows) + 1}' if rows else None
    for column in ws.columns:
        letter = column[0].column_letter
        width = min(45, max(10, max(len(str(cell.value or '')) for cell in column) + 2))
        ws.column_dimensions[letter].width = width


def _xlsx_response(report_type, label, data, month_start, report_end):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = 'Report'
    branding = get_app_branding()
    _sheet_title(ws, f'{branding.app_name} — {label}', f'{month_start:%d %B %Y} to {report_end:%d %B %Y}')

    if report_type == 'compliance':
        summary = data['summary']
        ws.append(['Scheduled', summary['scheduled'], 'Held', summary['held'], 'Cancelled', summary['cancelled'], 'Pending', summary['pending'], 'Make-up', summary['makeup'], 'Completion %', summary['completion']])
        ws.append([])
        _append_table(ws, ['Date', 'Lecture', 'Subject', 'Code', 'Classes', 'Teacher', 'Type', 'Status'], [
            [row['date'], row['lecture_number'], row['offering'].subject.name, row['offering'].subject.code,
             row['offering'].class_codes_display, (row['offering'].lecturer.get_full_name() or row['offering'].lecturer.username) if row['offering'].lecturer else 'Unassigned',
             'Make-up' if row['source'] == 'MAKEUP' else 'Regular', row['state_label']]
            for row in data['rows']
        ])
        ws2 = wb.create_sheet('By Class')
        _append_table(ws2, ['Class', 'Programme', 'Scheduled', 'Held', 'Cancelled', 'Pending', 'Make-up', 'Completion %'], [
            [item['class_group'].code, item['class_group'].programme.code, item['scheduled'], item['held'], item['cancelled'], item['pending'], item['makeup'], item['completion']]
            for item in data['class_rows']
        ])
        ws3 = wb.create_sheet('By Teacher')
        _append_table(ws3, ['Teacher', 'Teacher ID', 'Scheduled', 'Held', 'Cancelled', 'Pending', 'Make-up', 'Completion %'], [
            [(item['lecturer'].get_full_name() or item['lecturer'].username) if item['lecturer'] else 'Unassigned', item['lecturer'].username if item['lecturer'] else '',
             item['scheduled'], item['held'], item['cancelled'], item['pending'], item['makeup'], item['completion']]
            for item in data['teacher_rows']
        ])
    elif report_type == 'monthly_lecturer':
        _append_table(ws, ['#', 'Teacher Name', 'Class', 'Lec in timetable', 'Date', 'Day', 'Status', 'Remarks'], [
            [index,
             (item['lecturer'].get_full_name() or item['lecturer'].username) if item['lecturer'] else 'Unassigned',
             item['class_group'].code, item['lec_in_timetable'], item['date'], item['day'], item['status'], item['remarks']]
            for index, item in enumerate(data['rows'], start=1)
        ])
    elif report_type == 'timetable_compliance':
        _append_table(ws, ['Teacher Name', 'Class', 'Subject', 'Lec in timetable', 'Expected', 'Held', 'Missing', 'Make-up Held', 'Delivered', 'Compliance %'], [
            [(item['lecturer'].get_full_name() or item['lecturer'].username) if item['lecturer'] else 'Unassigned',
             item['class_group'].code, item['offering'].subject.name, item['lec_in_timetable'],
             item['expected'], item['held'], item['missing'], item['makeup_held'], item['delivered'], item['compliance']]
            for item in data['rows']
        ])
    elif report_type == 'daily':
        _append_table(ws, ['Lecture', 'Subject', 'Code', 'Classes', 'Teacher', 'Type', 'Status', 'Present', 'Absent'], [
            [row['lecture_number'], row['offering'].subject.name, row['offering'].subject.code, row['offering'].class_codes_display,
             (row['offering'].lecturer.get_full_name() or row['offering'].lecturer.username) if row['offering'].lecturer else 'Unassigned',
             {'MAKEUP': 'Make-up', 'ADDITIONAL': 'Additional'}.get(row['source'], 'Regular'), row['state_label'], row['present'], row['absent']]
            for row in data['rows']
        ])
    elif report_type == 'class':
        _append_table(ws, ['Subject', 'Code', 'Scheduled', 'Held', 'Cancelled', 'Pending', 'Make-up', 'Present marks', 'Absent marks', 'Attendance %'], [
            [item['offering'].subject.name, item['offering'].subject.code, item['scheduled'], item['held'], item['cancelled'], item['pending'], item['makeup'], item['present'], item['absent'], item['attendance_rate']]
            for item in data['subject_rows']
        ])
        ws2 = wb.create_sheet('Students')
        _append_table(ws2, ['Registration', 'Student', 'Present', 'Absent', 'Held marks', 'Attendance %'], [
            [item['student'].user.username, item['student'].user.get_full_name() or item['student'].user.username, item['present'], item['absent'], item['held_marks'], item['attendance_rate']]
            for item in data['student_rows']
        ])
    elif report_type == 'student':
        student = data.get('student')
        if student:
            ws.append(['Student', student.user.get_full_name() or student.user.username, 'Registration', student.user.username])
            ws.append([])
        _append_table(ws, ['Date', 'Lecture', 'Subject', 'Code', 'Type', 'Status'], [
            [item['session'].lecture_date, item['session'].lecture_number, item['offering'].subject.name, item['offering'].subject.code, item['source'], item['record'].get_status_display()]
            for item in data['history']
        ])
    elif report_type == 'defaulters':
        _append_table(ws, ['Registration', 'Student', 'Subject', 'Classes', 'Allowed absences', 'Term absences', 'Excess', 'Month absences', 'Attendance %', 'Fine due'], [
            [item['registration'], item['student_name'], item['offering'].subject.name, item['offering'].class_codes_display, item['allowed'], item['term_absent'], item['excess'], item['month_absent'], item['attendance_rate'], float(item['fine_balance'])]
            for item in data['rows']
        ])
    elif report_type == 'fines':
        _append_table(ws, ['Date/time', 'Registration', 'Student', 'Subject', 'Classes', 'Kind', 'Amount', 'Note', 'Actor'], [
            [timezone.localtime(item.created_at).replace(tzinfo=None), item.student.user.username, item.student.user.get_full_name() or item.student.user.username,
             item.class_subject.subject.name, item.class_subject.class_codes_display, item.get_kind_display(), float(item.amount), item.note,
             (item.actor.get_full_name() or item.actor.username) if item.actor else 'System']
            for item in data['entries']
        ])
        ws2 = wb.create_sheet('Outstanding')
        _append_table(ws2, ['Registration', 'Student', 'Subject', 'Classes', 'Outstanding'], [
            [item['student__user__username'], (' '.join(filter(None, [item['student__user__first_name'], item['student__user__last_name']])) or item['student__user__username']),
             item['class_subject__subject__name'], item['offering'].class_codes_display if item.get('offering') else '', float(item['balance'])]
            for item in data['balances']
        ])

    stream = BytesIO()
    wb.save(stream)
    brand_slug = slugify(branding.app_name) or 'attendance'
    filename = f'{brand_slug}_{report_type}_{month_start:%Y_%m}.xlsx'
    response = HttpResponse(
        stream.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@role_required('ADMIN')
@require_GET
def reports(request):
    report_type = request.GET.get('report', 'compliance')
    valid_types = dict(REPORT_TYPES)
    if report_type not in valid_types:
        report_type = 'compliance'

    month_start, month_end, report_end = _month_bounds(request.GET.get('month', ''))
    filters = _filter_models(request, month_start, report_end)
    offerings = list(_offering_queryset(month_start, report_end, filters))

    if report_type == 'monthly_lecturer':
        data = _monthly_lecturer_report(offerings, month_start, report_end, filters)
    elif report_type == 'timetable_compliance':
        data = _timetable_compliance_report(offerings, month_start, report_end, filters)
    elif report_type == 'daily':
        selected_date = _parse_date(request.GET.get('date', ''), report_end)
        # For a daily report the relevant terms/sections come from the date itself.
        daily_filters = _filter_models(request, selected_date, selected_date)
        offerings = list(_offering_queryset(selected_date, selected_date, daily_filters))
        filters = daily_filters
        data = _daily_report(offerings, selected_date, _filtered_student_ids(filters, selected_date, selected_date))
    elif report_type == 'class':
        selected_class = filters['selected_class']
        if not selected_class:
            selected_class = filters['classes'].first()
            if selected_class:
                filters['class_id'] = selected_class.pk
                filters['selected_class'] = selected_class
                class_filters = {**filters, 'class_id': selected_class.pk}
                offerings = list(_offering_queryset(month_start, report_end, class_filters))
        data = _class_report(offerings, selected_class, month_start, report_end)
    elif report_type == 'student':
        data = _student_report(request, offerings, month_start, report_end, filters)
    elif report_type == 'defaulters':
        data = _defaulters_report(offerings, month_start, report_end, _filtered_student_ids(filters, month_start, report_end))
    elif report_type == 'fines':
        data = _fines_report(offerings, month_start, report_end, _filtered_student_ids(filters, month_start, report_end))
    else:
        data = _compliance_report(offerings, month_start, report_end, filters)

    if request.GET.get('export') == 'xlsx':
        return _xlsx_response(report_type, valid_types[report_type], data, month_start, report_end)

    query = request.GET.copy()
    query.pop('export', None)
    if 'report' not in query:
        query['report'] = report_type
    if 'month' not in query:
        query['month'] = month_start.strftime('%Y-%m')
    xlsx_query = query.copy()
    xlsx_query['export'] = 'xlsx'

    context = {
        'report_types': REPORT_TYPES,
        'report_type': report_type,
        'report_label': valid_types[report_type],
        'month_start': month_start,
        'month_end': month_end,
        'report_end': report_end,
        'month_value': month_start.strftime('%Y-%m'),
        'data': data,
        'xlsx_url': f'{request.path}?{xlsx_query.urlencode()}',
        **filters,
    }
    return render(request, 'reports/index.html', context)
