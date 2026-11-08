from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Programme(models.Model):
    code = models.CharField(max_length=24, unique=True)
    name = models.CharField(max_length=180)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f'{self.code} — {self.name}'


class AcademicTerm(models.Model):
    name = models.CharField(max_length=90, unique=True, help_text='Example: Fall 2026')
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ['-start_date']

    def clean(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError('End date cannot precede start date.')

    def __str__(self):
        return self.name


class ClassGroup(models.Model):
    code = models.CharField(max_length=48, help_text='Example: BSCS-S1')
    name = models.CharField(max_length=120, blank=True, default='', help_text='Example: Semester 1')
    programme = models.ForeignKey(Programme, on_delete=models.PROTECT, related_name='classes')
    term = models.ForeignKey(AcademicTerm, on_delete=models.PROTECT, related_name='classes')
    semester_number = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ['programme__code', 'semester_number', 'code']
        constraints = [models.UniqueConstraint(fields=['term', 'code'], name='unique_class_code_per_term')]

    def save(self, *args, **kwargs):
        if not self.name:
            self.name = f'Semester {self.semester_number}'
        super().save(*args, **kwargs)

    def __str__(self):
        label = self.name or f'Semester {self.semester_number}'
        return f'{self.code} — {label} ({self.term.name})'


class Subject(models.Model):
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=180)
    short_name = models.CharField(max_length=40)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f'{self.short_name} — {self.name}'


class StudentProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='student_profile')

    def __str__(self):
        return f'{self.user.get_full_name()} ({self.user.username})'


class ClassMembership(models.Model):
    student = models.ForeignKey(StudentProfile, on_delete=models.PROTECT, related_name='memberships')
    term = models.ForeignKey(AcademicTerm, on_delete=models.PROTECT, related_name='memberships')
    class_group = models.ForeignKey(ClassGroup, on_delete=models.PROTECT, related_name='memberships')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['student', 'term'], name='unique_student_term_membership')]

    def clean(self):
        if self.class_group_id and self.term_id and self.class_group.term_id != self.term_id:
            raise ValidationError('The class must belong to the selected academic term.')

    def __str__(self):
        return f'{self.student} / {self.class_group}'


class ClassSubject(models.Model):
    """A subject-based teaching section.

    ``class_group`` remains as the primary/legacy class so existing attendance and
    fine records stay compatible. ``class_groups`` is the source of truth for the
    classes that share this section. The CSV importer merges rows when the same
    subject is taught by the same lecturer in the same term.
    """
    class_group = models.ForeignKey(ClassGroup, on_delete=models.PROTECT, related_name='class_subjects')
    class_groups = models.ManyToManyField(ClassGroup, related_name='subject_sections', blank=True)
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name='class_subjects')
    section_code = models.CharField(
        max_length=60,
        blank=True,
        default='',
        help_text='Subject-based section label. If blank, the subject short name is used.',
    )
    lecturer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='teaching_assignments',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['class_group__code', 'subject__short_name']
        constraints = [models.UniqueConstraint(fields=['class_group', 'subject'], name='unique_subject_per_class')]

    def clean(self):
        if self.lecturer_id and self.lecturer.role != 'LECTURER':
            raise ValidationError('Assigned user must have Lecturer role.')

    def save(self, *args, **kwargs):
        if not self.section_code and self.subject_id:
            self.section_code = self.subject.short_name
        super().save(*args, **kwargs)

    @property
    def term(self):
        # class_group is deliberately retained for compatibility and always points
        # at one of the linked classes for active imported sections.
        return self.class_group.term if self.class_group_id else None

    def linked_class_ids(self):
        """Return all classes in the section, with legacy primary-class fallback."""
        ids = [group.pk for group in self.class_groups.all()] if self.pk else []
        return ids or ([self.class_group_id] if self.class_group_id else [])

    @property
    def class_codes_display(self):
        if not self.pk:
            return self.class_group.code if self.class_group_id else ''
        codes = list(self.class_groups.order_by('programme__code', 'semester_number', 'code').values_list('code', flat=True))
        if not codes and self.class_group_id:
            codes = [self.class_group.code]
        return ', '.join(codes)

    @property
    def class_count(self):
        if not self.pk:
            return 1 if self.class_group_id else 0
        count = self.class_groups.count()
        return count or (1 if self.class_group_id else 0)

    def __str__(self):
        section = self.section_code or self.subject.short_name
        classes = self.class_codes_display or 'No class'
        return f'{classes} — {self.subject.short_name} [{section}]'


class WeeklySchedule(models.Model):
    DAYS = [
        (0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'), (3, 'Thursday'),
        (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday'),
    ]
    class_subject = models.ForeignKey(ClassSubject, on_delete=models.PROTECT, related_name='weekly_schedules')
    weekday = models.PositiveSmallIntegerField(choices=DAYS)
    lecture_number = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ['weekday', 'lecture_number', 'class_subject__class_group__code']
        constraints = [models.UniqueConstraint(fields=['class_subject', 'weekday', 'lecture_number'], name='unique_subject_day_lecture')]

    def clean(self):
        if self.lecture_number is not None and not (1 <= self.lecture_number <= 20):
            raise ValidationError('Lecture number must be between 1 and 20.')
        if not self.class_subject_id or self.weekday is None or not self.lecture_number:
            return
        subject_section = self.class_subject
        class_ids = subject_section.linked_class_ids()
        same_slot = WeeklySchedule.objects.filter(
            weekday=self.weekday, lecture_number=self.lecture_number,
            class_subject__class_group__term=subject_section.class_group.term,
        )
        if self.pk:
            same_slot = same_slot.exclude(pk=self.pk)
        if class_ids and same_slot.filter(
            Q(class_subject__class_groups__in=class_ids) |
            Q(class_subject__class_group_id__in=class_ids, class_subject__class_groups__isnull=True)
        ).distinct().exists():
            raise ValidationError(
                'One of the linked classes already has a different subject in this day and lecture number.'
            )
        if subject_section.lecturer_id and same_slot.filter(
            class_subject__lecturer_id=subject_section.lecturer_id,
            class_subject__class_groups__isnull=False,
        ).exists():
            raise ValidationError(
                'This lecturer already teaches another subject in this day and lecture number.'
            )

    def __str__(self):
        return f'{self.class_subject} / {self.get_weekday_display()} L{self.lecture_number}'


class AppBranding(models.Model):
    """Singleton, super-admin-managed product branding used across the UI."""

    app_name = models.CharField(max_length=80, default='Clasvanta')
    subtitle = models.CharField(max_length=120, default='Academic Attendance & Management')
    institute_name = models.CharField(max_length=140, default='Clasvanta')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='branding_updates',
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = 'application branding'
        verbose_name_plural = 'application branding'

    def clean(self):
        self.app_name = (self.app_name or '').strip()
        self.subtitle = (self.subtitle or '').strip()
        self.institute_name = (self.institute_name or '').strip()
        if not self.app_name:
            raise ValidationError('Application name is required.')
        if not self.subtitle:
            raise ValidationError('Application subtitle is required.')
        if not self.institute_name:
            raise ValidationError('Institute name is required.')

    def save(self, *args, **kwargs):
        # The application uses one branding row only. Keeping the canonical row
        # at pk=1 avoids institution-specific IDs leaking into templates/routes.
        self.pk = 1
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.app_name
