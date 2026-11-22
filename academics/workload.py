"""Shared weekly timetable/workload helpers for lecturer and student profiles."""
from django.db.models import Q

from .models import AcademicTerm, WeeklySchedule


def _weekly_payload(schedules):
    days = {
        weekday: {'weekday': weekday, 'label': label, 'lectures': []}
        for weekday, label in WeeklySchedule.DAYS
    }
    subject_ids = set()
    section_ids = set()
    class_ids = set()
    lecturer_ids = set()
    merged_section_ids = set()
    teaching_days = set()

    for schedule in schedules:
        offering = schedule.class_subject
        linked_classes = list(offering.class_groups.all())
        if not linked_classes and offering.class_group_id:
            linked_classes = [offering.class_group]
        linked_classes = sorted(
            linked_classes,
            key=lambda group: (group.programme.code, group.semester_number, group.code),
        )
        class_codes = ', '.join(group.code for group in linked_classes)
        class_count = len(linked_classes)

        days[schedule.weekday]['lectures'].append({
            'schedule': schedule,
            'offering': offering,
            'lecture_number': schedule.lecture_number,
            'subject': offering.subject,
            'lecturer': offering.lecturer,
            'class_codes': class_codes,
            'class_count': class_count,
            'merged': class_count > 1,
        })
        teaching_days.add(schedule.weekday)
        subject_ids.add(offering.subject_id)
        section_ids.add(offering.pk)
        class_ids.update(group.pk for group in linked_classes)
        if offering.lecturer_id:
            lecturer_ids.add(offering.lecturer_id)
        if class_count > 1:
            merged_section_ids.add(offering.pk)

    return {
        'days': [days[weekday] for weekday, _ in WeeklySchedule.DAYS],
        'summary': {
            'lecture_count': len(schedules),
            'subject_count': len(subject_ids),
            'section_count': len(section_ids),
            'class_count': len(class_ids),
            'lecturer_count': len(lecturer_ids),
            'teaching_days': len(teaching_days),
            'merged_section_count': len(merged_section_ids),
        },
    }


def weekly_workload_for_offerings(offerings):
    """Return recurring weekly timetable rows for an already-scoped offering list."""
    offering_ids = [offering.pk for offering in offerings]
    if not offering_ids:
        return _weekly_payload([])
    schedules = list(
        WeeklySchedule.objects.filter(class_subject_id__in=offering_ids)
        .select_related(
            'class_subject__subject',
            'class_subject__lecturer',
            'class_subject__class_group__programme',
        )
        .prefetch_related('class_subject__class_groups__programme')
        .order_by('weekday', 'lecture_number', 'class_subject__subject__name')
    )
    return _weekly_payload(schedules)


def weekly_workload_for_lecturer(user):
    """Return the active-term recurring weekly workload assigned to one lecturer."""
    active_term = AcademicTerm.objects.filter(is_active=True).first()
    if not active_term:
        payload = _weekly_payload([])
        payload['active_term'] = None
        return payload

    schedules = list(
        WeeklySchedule.objects.filter(class_subject__lecturer=user)
        .filter(
            Q(class_subject__class_groups__term=active_term)
            | Q(
                class_subject__class_group__term=active_term,
                class_subject__class_groups__isnull=True,
            )
        )
        .select_related(
            'class_subject__subject',
            'class_subject__lecturer',
            'class_subject__class_group__programme',
        )
        .prefetch_related('class_subject__class_groups__programme')
        .distinct()
        .order_by('weekday', 'lecture_number', 'class_subject__subject__name')
    )
    payload = _weekly_payload(schedules)
    payload['active_term'] = active_term
    return payload
