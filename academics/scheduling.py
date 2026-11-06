"""Explicit conflict checks for schedule/teacher changes in active academic terms."""
from django.core.exceptions import ValidationError
from .models import WeeklySchedule


def check_teacher_schedule(section, lecturer):
    """Prevent assigning a lecturer to two different sections in the same slot.

    One merged section is one lesson, even when it includes multiple classes.
    """
    if not lecturer.is_active:
        raise ValidationError('This lecturer is inactive. Activate the account before assignment.')
    slots = list(section.weekly_schedules.values_list('weekday', 'lecture_number'))
    if not slots:
        return
    for weekday, number in slots:
        clashes = WeeklySchedule.objects.filter(
            weekday=weekday, lecture_number=number,
            class_subject__lecturer=lecturer,
            class_subject__class_group__term=section.class_group.term,
            class_subject__class_groups__isnull=False,
        ).exclude(class_subject=section)
        if clashes.exists():
            other = clashes.select_related('class_subject__subject').first()
            raise ValidationError(
                f'Teacher already has {other.class_subject.subject.code} '
                f'on {other.get_weekday_display()}, Lecture {number}.'
            )


def check_class_section_join(group, section):
    """Joining a new class to a merged section cannot double-book that class."""
    for slot in section.weekly_schedules.all():
        conflict = WeeklySchedule.objects.filter(
            class_subject__class_groups=group,
            weekday=slot.weekday, lecture_number=slot.lecture_number,
        ).exclude(class_subject=section)
        if conflict.exists():
            raise ValidationError(
                f'{group.code} already has a different lecture on '
                f'{slot.get_weekday_display()}, Lecture {slot.lecture_number}.'
            )
