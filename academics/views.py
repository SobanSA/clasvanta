import csv
from decimal import Decimal, InvalidOperation
from datetime import date

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.models import User
from accounts.views import role_required
from attendance.models import AttendanceAudit, AttendanceRecord, AttendanceSettings, LectureSession, MakeupClass
from fines.models import FineLedgerEntry, FinePolicy
from fines.services import reconcile_fine
from .imports import import_students, import_structure, parse_upload, validate_rows, _password
from .scheduling import check_teacher_schedule, check_class_section_join
from .models import AcademicTerm, AppBranding, ClassGroup, ClassMembership, ClassSubject, Programme, StudentProfile, Subject, WeeklySchedule


@role_required('ADMIN')
def admin_dashboard(request):
    today = timezone.localdate()
    month_start = today.replace(day=1)

    # Regular timetable counts are based on recurring WeeklySchedule rows. A class
    # only becomes "held" after attendance is explicitly submitted; pending or
    # cancelled occurrences therefore do not inflate the held figure.
    today_regular = WeeklySchedule.objects.filter(
        weekday=today.weekday(),
    ).filter(
        Q(class_subject__class_groups__term__is_active=True) |
        Q(class_subject__class_group__term__is_active=True, class_subject__class_groups__isnull=True)
    ).distinct()
    scheduled_keys = set(today_regular.values_list('class_subject_id', 'lecture_number'))
    submitted_keys = set(LectureSession.objects.filter(
        lecture_date=today, status='SUBMITTED',
    ).values_list('class_subject_id', 'lecture_number'))
    today_scheduled = len(scheduled_keys)
    today_held = len(scheduled_keys & submitted_keys)

    active_makeup_scope = (
        Q(class_subject__class_groups__term__is_active=True) |
        Q(class_subject__class_group__term__is_active=True, class_subject__class_groups__isnull=True)
    )
    makeup_today = MakeupClass.objects.filter(
        active_makeup_scope, lecture_date=today, status=MakeupClass.APPROVED,
    ).distinct().count()
    makeup_month = MakeupClass.objects.filter(
        active_makeup_scope, lecture_date__range=(month_start, today), status=MakeupClass.APPROVED,
    ).distinct().count()

    context = {
        'student_count': StudentProfile.objects.count(),
        'lecturer_count': User.objects.filter(role='LECTURER', is_active=True).count(),
        'class_count': ClassGroup.objects.filter(term__is_active=True).count(),
        'today_sessions': LectureSession.objects.filter(lecture_date=today, status='SUBMITTED').count(),
        'today_scheduled': today_scheduled,
        'today_held': today_held,
        'makeup_today': makeup_today,
        'makeup_month': makeup_month,
        'month_start': month_start,
        'recent_sessions': LectureSession.objects.select_related(
            'class_subject__class_group', 'class_subject__subject', 'submitted_by'
        ).order_by('-submitted_at')[:8],
        'recent_audits': AttendanceAudit.objects.select_related(
            'actor', 'student__user', 'session__class_subject__subject'
        ).order_by('-created_at')[:6],
        'active_terms': AcademicTerm.objects.filter(is_active=True),
    }
    return render(request, 'admin_panel/dashboard.html', context)


@role_required('STUDENT')
def student_dashboard(request):
    # Kept as the compatibility entry point used by accounts.views.dashboard.
    # The v2.7 student portal implementation lives in academics.student_portal.
    from .student_portal import dashboard as portal_dashboard
    return portal_dashboard(request)


@role_required('ADMIN')
def academic_structure(request):
    active = AcademicTerm.objects.filter(is_active=True).first()
    programmes = Programme.objects.all().order_by('code')
    selected_programme = None
    selected_class = None
    classes = ClassGroup.objects.none()
    offerings = ClassSubject.objects.none()

    if active:
        programme_id = request.GET.get('program')
        if programme_id and programme_id.isdigit():
            selected_programme = programmes.filter(pk=int(programme_id)).first()
        if selected_programme is None:
            selected_programme = programmes.filter(classes__term=active).distinct().first()

        if selected_programme:
            classes = ClassGroup.objects.filter(
                term=active, programme=selected_programme
            ).annotate(
                assigned_course_count=Count('subject_sections', distinct=True)
            ).order_by('semester_number', 'code')

            class_id = request.GET.get('class')
            if class_id and class_id.isdigit():
                selected_class = classes.filter(pk=int(class_id)).first()
            if selected_class is None:
                selected_class = classes.first()

        if selected_class:
            offerings = ClassSubject.objects.filter(
                class_groups=selected_class
            ).select_related(
                'subject', 'lecturer', 'class_group'
            ).prefetch_related(
                'class_groups__programme', 'weekly_schedules'
            ).distinct().order_by('subject__code')

    rows = []
    missing_teacher_count = 0
    merged_count = 0
    for offering in offerings:
        linked_classes = list(offering.class_groups.all())
        if not offering.lecturer_id:
            missing_teacher_count += 1
        if len(linked_classes) > 1:
            merged_count += 1
        rows.append({
            'offering': offering,
            'linked_classes': linked_classes,
            'is_merged': len(linked_classes) > 1,
        })

    return render(request, 'academics/structure.html', {
        'active_term': active,
        'programmes': programmes,
        'selected_programme': selected_programme,
        'classes': classes,
        'selected_class': selected_class,
        'rows': rows,
        'course_count': len(rows),
        'missing_teacher_count': missing_teacher_count,
        'merged_count': merged_count,
    })


def _admin_context():
    terms = AcademicTerm.objects.order_by('-start_date')
    active = terms.filter(is_active=True).first()
    groups = ClassGroup.objects.filter(term=active).select_related('programme') if active else ClassGroup.objects.none()
    return {
        'programmes': Programme.objects.all(),
        'terms': terms,
        'active_term': active,
        'groups': groups,
        'subjects': Subject.objects.all(),
        'offerings': ClassSubject.objects.filter(class_groups__term=active).select_related(
            'class_group', 'subject', 'lecturer'
        ).prefetch_related('class_groups__programme', 'weekly_schedules').distinct() if active else ClassSubject.objects.none(),
        'lecturers': User.objects.filter(role='LECTURER', is_active=True).order_by('first_name', 'username'),
        'schedule': WeeklySchedule.objects.filter(class_subject__class_groups__term=active).select_related(
            'class_subject__class_group', 'class_subject__subject'
        ).distinct() if active else WeeklySchedule.objects.none(),
        'fine_policy': FinePolicy.objects.filter(term=active).first() if active else None,
        'hours': AttendanceSettings.objects.filter(pk=1).first(),
        'new_lecturer': None,
    }


@role_required('ADMIN')
@require_http_methods(['GET', 'POST'])
def academic_setup(request):
    if request.method == 'POST':
        action = request.POST.get('action', '')
        try:
            with transaction.atomic():
                if action == 'programme':
                    obj = Programme(
                        code=request.POST['code'].strip().upper(),
                        name=request.POST['name'].strip(),
                    )
                    obj.full_clean(); obj.save()

                elif action == 'edit_programme':
                    obj = Programme.objects.get(pk=int(request.POST['id']))
                    obj.code = request.POST['code'].strip().upper()
                    obj.name = request.POST['name'].strip()
                    obj.full_clean(); obj.save()

                elif action == 'term':
                    start = date.fromisoformat(request.POST['start_date'])
                    end = date.fromisoformat(request.POST['end_date'])
                    AcademicTerm.objects.filter(is_active=True).update(is_active=False)
                    obj = AcademicTerm(
                        name=request.POST['name'].strip(),
                        start_date=start,
                        end_date=end,
                        is_active=True,
                    )
                    obj.full_clean(); obj.save()

                elif action == 'class':
                    active = AcademicTerm.objects.get(is_active=True)
                    semester = int(request.POST['semester_number'])
                    obj = ClassGroup(
                        code=request.POST['code'].strip().upper(),
                        name=request.POST.get('name', '').strip() or f'Semester {semester}',
                        programme_id=int(request.POST['programme']),
                        term=active,
                        semester_number=semester,
                    )
                    obj.full_clean(); obj.save()

                elif action == 'edit_class':
                    obj = ClassGroup.objects.get(pk=int(request.POST['id']))
                    semester = int(request.POST['semester_number'])
                    obj.code = request.POST['code'].strip().upper()
                    obj.name = request.POST.get('name', '').strip() or f'Semester {semester}'
                    obj.programme_id = int(request.POST['programme'])
                    obj.semester_number = semester
                    obj.full_clean(); obj.save()

                elif action == 'subject':
                    obj = Subject(
                        code=request.POST['code'].strip().upper(),
                        name=request.POST['name'].strip(),
                        short_name=request.POST['short_name'].strip(),
                    )
                    obj.full_clean(); obj.save()

                elif action == 'edit_subject':
                    obj = Subject.objects.get(pk=int(request.POST['id']))
                    obj.code = request.POST['code'].strip().upper()
                    obj.name = request.POST['name'].strip()
                    obj.short_name = request.POST['short_name'].strip()
                    obj.full_clean(); obj.save()

                elif action == 'assign_subject':
                    group = ClassGroup.objects.get(pk=int(request.POST['class_group']), term__is_active=True)
                    subject = Subject.objects.get(pk=int(request.POST['subject']))
                    obj = ClassSubject(
                        class_group=group,
                        subject=subject,
                        section_code=request.POST.get('section_code', '').strip() or subject.short_name,
                    )
                    obj.full_clean(); obj.save()
                    obj.class_groups.add(group)

                elif action == 'lecturer':
                    username = request.POST['username'].strip()
                    full_name = request.POST['name'].strip()
                    if not full_name or not username:
                        raise ValueError('Username and name are required.')
                    password = _password()
                    user = User(
                        username=username,
                        first_name=full_name,
                        role='LECTURER',
                        must_change_password=True,
                    )
                    user.set_password(password)
                    user.full_clean(); user.save()
                    request.session['new_lecturer'] = {'username': username, 'password': password}

                elif action == 'assign_lecturer':
                    offering = ClassSubject.objects.get(
                        pk=int(request.POST['offering']), class_groups__term__is_active=True
                    )
                    lecturer = User.objects.get(pk=int(request.POST['lecturer']), role='LECTURER', is_active=True)
                    check_teacher_schedule(offering, lecturer)
                    offering.lecturer = lecturer
                    offering.section_code = request.POST.get('section_code', '').strip() or offering.section_code or offering.subject.short_name
                    offering.full_clean(); offering.save()

                elif action == 'schedule':
                    offering = ClassSubject.objects.get(
                        pk=int(request.POST['offering']), class_groups__term__is_active=True
                    )
                    obj = WeeklySchedule(
                        class_subject=offering,
                        weekday=int(request.POST['weekday']),
                        lecture_number=int(request.POST['lecture_number']),
                    )
                    obj.full_clean(); obj.save()

                elif action == 'hours':
                    from datetime import time
                    policy, _ = AttendanceSettings.objects.get_or_create(pk=1)
                    policy.working_start = time.fromisoformat(request.POST['working_start'])
                    policy.working_end = time.fromisoformat(request.POST['working_end'])
                    policy.full_clean(); policy.save()

                elif action == 'fine_policy':
                    active = AcademicTerm.objects.get(is_active=True)
                    allowed = int(request.POST['allowed_absences'])
                    rate = Decimal(request.POST['rate_per_extra_absence'])
                    if allowed < 0 or rate < 0:
                        raise ValueError('Fine settings cannot be negative.')
                    FinePolicy.objects.update_or_create(
                        term=active,
                        defaults={'allowed_absences': allowed, 'rate_per_extra_absence': rate},
                    )
                    for group in ClassGroup.objects.filter(term=active):
                        students = StudentProfile.objects.filter(memberships__class_group=group)
                        offerings = ClassSubject.objects.filter(class_groups=group).distinct()
                        for student in students:
                            student = StudentProfile.objects.select_for_update().get(pk=student.pk)
                            for offering in offerings:
                                reconcile_fine(student, offering, actor=request.user)
                else:
                    raise ValueError('Unknown setup action.')
            messages.success(request, 'Saved successfully.')
            return redirect('academic_setup')
        except (
            ValueError,
            KeyError,
            ValidationError,
            IntegrityError,
            Programme.DoesNotExist,
            AcademicTerm.DoesNotExist,
            ClassSubject.DoesNotExist,
            ClassGroup.DoesNotExist,
            Subject.DoesNotExist,
            User.DoesNotExist,
            InvalidOperation,
        ) as exc:
            messages.error(request, f'Could not save: {exc}')

    context = _admin_context()
    context['new_lecturer'] = request.session.pop('new_lecturer', None)
    return render(request, 'academics/setup.html', context)


@role_required('ADMIN')
@require_http_methods(['GET', 'POST'])
def bulk_import(request, kind):
    if kind not in ('students', 'structure'):
        raise Http404('Unsupported import type')

    preview = None
    errors = []
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'preview':
            try:
                raw_rows = parse_upload(request.FILES['file'])
                preview, errors = validate_rows(kind, raw_rows)
                if errors or not preview:
                    request.session.pop(f'import_{kind}', None)
                    if not errors:
                        errors.append('No valid records found.')
                else:
                    payload = {'rows': raw_rows}
                    if kind == 'students':
                        payload['term'] = AcademicTerm.objects.get(is_active=True).pk
                    request.session[f'import_{kind}'] = payload
            except (ValueError, KeyError, UnicodeError, AcademicTerm.DoesNotExist) as exc:
                errors = [str(exc)]

        elif action == 'confirm':
            payload = request.session.pop(f'import_{kind}', None)
            if not payload:
                errors = ['Import preview expired. Upload the file again.']
            else:
                if kind == 'students' and not AcademicTerm.objects.filter(
                    pk=payload.get('term'), is_active=True
                ).exists():
                    errors = ['The active academic term changed since preview. Please upload again.']
                    again = []
                else:
                    again, errors = validate_rows(kind, payload['rows'])

                if not errors and again:
                    try:
                        if kind == 'students':
                            credentials, stats = import_students(again)
                            messages.success(
                                request,
                                f'Student import complete for {stats["term"]}: '
                                f'{stats["created"]} created, {stats["updated"]} updated.',
                            )
                            if credentials:
                                response = HttpResponse(content_type='text/csv; charset=utf-8')
                                response['Content-Disposition'] = 'attachment; filename="student_one_time_credentials.csv"'
                                response['Cache-Control'] = 'no-store'
                                writer = csv.writer(response)
                                writer.writerow(['registration_number', 'student_name', 'class', 'temporary_password'])
                                writer.writerows(credentials)
                                return response
                            return redirect('bulk_import', kind='students')

                        credentials, stats = import_structure(again)
                        messages.success(
                            request,
                            f'Academic setup imported for {stats["term"]}: '
                            f'{stats["programmes"]} programmes, {stats["classes"]} classes, '
                            f'{stats["subjects"]} subjects, {stats["offerings"]} subject sections, '
                            f'{stats["teachers"]} teachers and {stats["schedules"]} weekly lectures processed.',
                        )
                        if credentials:
                            response = HttpResponse(content_type='text/csv; charset=utf-8')
                            response['Content-Disposition'] = 'attachment; filename="new_teacher_one_time_credentials.csv"'
                            response['Cache-Control'] = 'no-store'
                            writer = csv.writer(response)
                            writer.writerow(['teacher_id', 'teacher_name', 'temporary_password'])
                            writer.writerows(credentials)
                            return response
                        return redirect('bulk_import', kind='structure')
                    except (ValueError, IntegrityError, ValidationError) as exc:
                        errors = [f'Import cancelled (no partial import): {exc}']
                elif not errors:
                    errors = ['No valid records found.']

    return render(request, 'academics/import.html', {
        'kind': kind,
        'preview': preview,
        'errors': errors,
        'is_students': kind == 'students',
        'is_structure': kind == 'structure',
    })


@role_required('ADMIN')
def students_list(request):
    active = AcademicTerm.objects.filter(is_active=True).first()
    programmes = Programme.objects.all().order_by('code')
    selected_programme = None
    selected_class = None
    groups = ClassGroup.objects.none()
    memberships = ClassMembership.objects.none()

    if active:
        program_id = request.GET.get('program')
        class_id = request.GET.get('class')
        if program_id and program_id.isdigit():
            selected_programme = programmes.filter(pk=int(program_id)).first()
        if selected_programme:
            groups = ClassGroup.objects.filter(term=active, programme=selected_programme).order_by('semester_number','code')
        else:
            groups = ClassGroup.objects.filter(term=active).select_related('programme').order_by('programme__code','semester_number','code')
        if class_id and class_id.isdigit():
            selected_class = groups.filter(pk=int(class_id)).first()

        memberships = ClassMembership.objects.filter(term=active).select_related(
            'student__user', 'class_group__programme'
        ).order_by('class_group__programme__code','class_group__semester_number','student__user__username')
        if selected_programme:
            memberships = memberships.filter(class_group__programme=selected_programme)
        if selected_class:
            memberships = memberships.filter(class_group=selected_class)

    class_subject_map = {}
    if active:
        for group in ClassGroup.objects.filter(term=active):
            class_subject_map[group.pk] = list(
                ClassSubject.objects.filter(class_groups=group).select_related('subject','lecturer').distinct().order_by('subject__code')
            )

    rows=[]
    for m in memberships:
        rows.append({
            'membership': m,
            'offerings': class_subject_map.get(m.class_group_id, []),
        })

    return render(request, 'academics/students_list.html', {
        'active_term': active,
        'programmes': programmes,
        'groups': groups,
        'selected_programme': selected_programme,
        'selected_class': selected_class,
        'rows': rows,
        'student_count': len(rows),
    })


@role_required('ADMIN')
def student_attendance(request):
    """Admin lookup: assigned subjects first, then expandable held-class history."""
    active = AcademicTerm.objects.filter(is_active=True).first()
    memberships = ClassMembership.objects.none()
    selected = None
    selected_membership = None
    subject_rows = []
    summary = {
        'total': 0,
        'present': 0,
        'absent': 0,
        'percentage': None,
        'fine_total': Decimal('0.00'),
    }

    if active:
        memberships = ClassMembership.objects.filter(term=active).select_related(
            'student__user', 'class_group__programme'
        ).order_by('student__user__username')

        student_id = request.GET.get('student', '')
        if student_id.isdigit():
            selected_membership = memberships.filter(student_id=int(student_id)).first()
            if selected_membership:
                selected = selected_membership.student
                offerings = list(ClassSubject.objects.filter(
                    class_groups=selected_membership.class_group,
                ).select_related('subject', 'lecturer').prefetch_related('class_groups').distinct().order_by('subject__name'))
                policy, _ = FinePolicy.objects.get_or_create(term=active)

                for offering in offerings:
                    records = list(AttendanceRecord.objects.filter(
                        student=selected,
                        session__class_subject=offering,
                        session__status='SUBMITTED',
                    ).select_related(
                        'session__submitted_by', 'session__class_subject__subject'
                    ).order_by('-session__lecture_date', '-session__lecture_number'))
                    total = len(records)
                    present = sum(1 for record in records if record.status == AttendanceRecord.PRESENT)
                    absent = total - present
                    ledger_total = FineLedgerEntry.objects.filter(
                        student=selected,
                        class_subject=offering,
                    ).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
                    fine_due = max(Decimal('0.00'), ledger_total)
                    summary['total'] += total
                    summary['present'] += present
                    summary['absent'] += absent
                    summary['fine_total'] += fine_due
                    subject_rows.append({
                        'offering': offering,
                        'total': total,
                        'present': present,
                        'absent': absent,
                        'percentage': round((present * 100) / total, 1) if total else None,
                        'allowed_remaining': max(0, policy.allowed_absences - absent),
                        'fine_due': fine_due,
                        'history': records,
                    })

                if summary['total']:
                    summary['percentage'] = round((summary['present'] * 100) / summary['total'], 1)

    return render(request, 'academics/student_attendance.html', {
        'active_term': active,
        'memberships': memberships,
        'selected_student': selected,
        'selected_membership': selected_membership,
        'subject_rows': subject_rows,
        'summary': summary,
    })


@role_required('ADMIN')
@require_http_methods(['GET','POST'])
def student_add(request):
    active = AcademicTerm.objects.filter(is_active=True).first()
    groups = ClassGroup.objects.filter(term=active).select_related('programme').order_by('programme__code','semester_number','code') if active else ClassGroup.objects.none()
    new_student = request.session.pop('new_student', None)

    if request.method == 'POST':
        try:
            if not active:
                raise ValueError('Create or activate an academic term first.')
            reg = request.POST['registration_number'].strip().upper()
            name = request.POST['student_name'].strip()
            group = ClassGroup.objects.get(pk=int(request.POST['class_group']), term=active)
            if not reg or not name:
                raise ValueError('Registration number and student name are required.')
            if User.objects.filter(username__iexact=reg).exists():
                raise ValueError(f'{reg} already exists. Use the enrolled-students screen to verify the record.')
            password = _password()
            with transaction.atomic():
                user = User(username=reg, first_name=name, role='STUDENT', must_change_password=True)
                user.set_password(password)
                user.full_clean(); user.save()
                profile = StudentProfile.objects.create(user=user)
                membership = ClassMembership(student=profile, term=active, class_group=group)
                membership.full_clean(); membership.save()
            request.session['new_student'] = {
                'registration_number': reg,
                'student_name': name,
                'class_code': group.code,
                'password': password,
            }
            messages.success(request, 'Student created successfully. Copy the temporary password now.')
            return redirect('student_add')
        except (ValueError, KeyError, ValidationError, IntegrityError, ClassGroup.DoesNotExist) as exc:
            messages.error(request, f'Could not add student: {exc}')

    return render(request, 'academics/student_add.html', {
        'active_term': active,
        'groups': groups,
        'new_student': new_student,
    })


@role_required('ADMIN')
@require_http_methods(['GET','POST'])
def programmes_manage(request):
    if request.method == 'POST':
        try:
            action=request.POST.get('action','add')
            if action == 'add':
                obj=Programme(code=request.POST['code'].strip().upper(), name=request.POST['name'].strip())
            elif action == 'edit':
                obj=Programme.objects.get(pk=int(request.POST['id']))
                obj.code=request.POST['code'].strip().upper(); obj.name=request.POST['name'].strip()
            else:
                raise ValueError('Unknown action.')
            obj.full_clean(); obj.save(); messages.success(request,'Programme saved.')
            return redirect('programmes_manage')
        except (ValueError, KeyError, ValidationError, IntegrityError, Programme.DoesNotExist) as exc:
            messages.error(request,f'Could not save programme: {exc}')
    return render(request,'academics/programmes.html',{'programmes':Programme.objects.all().order_by('code')})


@role_required('ADMIN')
@require_http_methods(['GET','POST'])
def terms_manage(request):
    if request.method == 'POST':
        try:
            action=request.POST.get('action','add')
            with transaction.atomic():
                if action == 'add':
                    obj=AcademicTerm(
                        name=request.POST['name'].strip(),
                        start_date=date.fromisoformat(request.POST['start_date']),
                        end_date=date.fromisoformat(request.POST['end_date']),
                        is_active=bool(request.POST.get('is_active')),
                    )
                    if obj.is_active:
                        AcademicTerm.objects.filter(is_active=True).update(is_active=False)
                elif action == 'edit':
                    obj=AcademicTerm.objects.get(pk=int(request.POST['id']))
                    obj.name=request.POST['name'].strip()
                    obj.start_date=date.fromisoformat(request.POST['start_date'])
                    obj.end_date=date.fromisoformat(request.POST['end_date'])
                elif action == 'activate':
                    obj=AcademicTerm.objects.get(pk=int(request.POST['id']))
                    AcademicTerm.objects.filter(is_active=True).update(is_active=False)
                    obj.is_active=True
                else:
                    raise ValueError('Unknown action.')
                obj.full_clean(); obj.save()
            messages.success(request,'Academic term saved.')
            return redirect('terms_manage')
        except (ValueError, KeyError, ValidationError, IntegrityError, AcademicTerm.DoesNotExist) as exc:
            messages.error(request,f'Could not save term: {exc}')
    return render(request,'academics/terms.html',{'terms':AcademicTerm.objects.order_by('-start_date')})


@role_required('ADMIN')
@require_http_methods(['GET','POST'])
def classes_manage(request):
    active=AcademicTerm.objects.filter(is_active=True).first()
    if request.method == 'POST':
        try:
            if not active: raise ValueError('Create or activate a term first.')
            action=request.POST.get('action','add')
            semester=int(request.POST['semester_number'])
            if action == 'add':
                obj=ClassGroup(term=active)
            elif action == 'edit':
                obj=ClassGroup.objects.get(pk=int(request.POST['id']), term=active)
            else: raise ValueError('Unknown action.')
            obj.code=request.POST['code'].strip().upper()
            obj.name=request.POST.get('name','').strip() or f'Semester {semester}'
            obj.programme_id=int(request.POST['programme'])
            obj.semester_number=semester
            obj.full_clean(); obj.save(); messages.success(request,'Class saved.')
            return redirect('classes_manage')
        except (ValueError, KeyError, ValidationError, IntegrityError, ClassGroup.DoesNotExist) as exc:
            messages.error(request,f'Could not save class: {exc}')
    groups=ClassGroup.objects.filter(term=active).select_related('programme').annotate(course_count=Count('subject_sections', distinct=True)).order_by('programme__code','semester_number','code') if active else ClassGroup.objects.none()
    return render(request,'academics/classes.html',{'active_term':active,'programmes':Programme.objects.all().order_by('code'),'groups':groups})


@role_required('ADMIN')
@require_http_methods(['GET','POST'])
def subjects_manage(request):
    if request.method == 'POST':
        try:
            action=request.POST.get('action','add')
            if action == 'add': obj=Subject()
            elif action == 'edit': obj=Subject.objects.get(pk=int(request.POST['id']))
            else: raise ValueError('Unknown action.')
            obj.code=request.POST['code'].strip().upper()
            obj.name=request.POST['name'].strip()
            obj.short_name=request.POST['short_name'].strip()
            obj.full_clean(); obj.save(); messages.success(request,'Subject saved.')
            return redirect('subjects_manage')
        except (ValueError, KeyError, ValidationError, IntegrityError, Subject.DoesNotExist) as exc:
            messages.error(request,f'Could not save subject: {exc}')
    return render(request,'academics/subjects.html',{'subjects':Subject.objects.all().order_by('code')})


@role_required('ADMIN')
@require_http_methods(['GET','POST'])
def teacher_assignments(request):
    active=AcademicTerm.objects.filter(is_active=True).first()
    lecturers=User.objects.filter(role='LECTURER', is_active=True).order_by('first_name','username')
    groups=ClassGroup.objects.filter(term=active).select_related('programme').order_by('programme__code','semester_number','code') if active else ClassGroup.objects.none()
    subjects=Subject.objects.all().order_by('code')

    if request.method == 'POST':
        try:
            if not active: raise ValueError('Create or activate a term first.')
            action=request.POST.get('action','assign')
            if action == 'assign':
                group=ClassGroup.objects.get(pk=int(request.POST['class_group']), term=active)
                subject=Subject.objects.get(pk=int(request.POST['subject']))
                lecturer=User.objects.get(pk=int(request.POST['lecturer']), role='LECTURER', is_active=True)
                existing=ClassSubject.objects.filter(class_groups=group, subject=subject).distinct().first()
                if existing:
                    check_teacher_schedule(existing, lecturer)
                    existing.lecturer=lecturer
                    if not existing.section_code:
                        existing.section_code=f'{subject.short_name}-{lecturer.username}'
                    existing.full_clean(); existing.save()
                else:
                    # Reuse an existing subject+teacher section in this term so the class joins the merged section.
                    target=ClassSubject.objects.filter(
                        class_groups__term=active, subject=subject, lecturer=lecturer
                    ).distinct().first()
                    if target:
                        check_class_section_join(group, target)
                        target.class_groups.add(group)
                        existing=target
                    else:
                        existing=ClassSubject(
                            class_group=group,
                            subject=subject,
                            lecturer=lecturer,
                            section_code=f'{subject.short_name}-{lecturer.username}',
                        )
                        existing.full_clean(); existing.save(); existing.class_groups.add(group)
                messages.success(request,f'{subject.code} assigned to {lecturer.get_full_name() or lecturer.username} for {group.code}.')
            elif action == 'update_section_teacher':
                offering=ClassSubject.objects.filter(pk=int(request.POST['offering']), class_groups__term=active).distinct().get()
                lecturer=User.objects.get(pk=int(request.POST['lecturer']), role='LECTURER', is_active=True)
                check_teacher_schedule(offering, lecturer)
                offering.lecturer=lecturer
                offering.section_code=request.POST.get('section_code','').strip() or f'{offering.subject.short_name}-{lecturer.username}'
                offering.full_clean(); offering.save()
                messages.success(request,'Teacher assignment updated for the complete subject section.')
            else:
                raise ValueError('Unknown action.')
            return redirect('teacher_assignments')
        except (ValueError, KeyError, ValidationError, IntegrityError, ClassGroup.DoesNotExist, Subject.DoesNotExist, User.DoesNotExist, ClassSubject.DoesNotExist) as exc:
            messages.error(request,f'Could not save teacher assignment: {exc}')

    offerings=ClassSubject.objects.filter(class_groups__term=active).select_related('subject','lecturer','class_group').prefetch_related('class_groups__programme').distinct().order_by('subject__code','section_code') if active else ClassSubject.objects.none()
    return render(request,'academics/teacher_assignments.html',{
        'active_term':active,'groups':groups,'subjects':subjects,'lecturers':lecturers,'offerings':offerings,
    })


@role_required('ADMIN')
@require_http_methods(['GET','POST'])
def lecture_schedule_manage(request):
    active=AcademicTerm.objects.filter(is_active=True).first()
    if request.method == 'POST':
        try:
            if not active: raise ValueError('Create or activate a term first.')
            action=request.POST.get('action','add')
            if action == 'add':
                offering=ClassSubject.objects.filter(pk=int(request.POST['offering']), class_groups__term=active).distinct().get()
                obj=WeeklySchedule(class_subject=offering, weekday=int(request.POST['weekday']), lecture_number=int(request.POST['lecture_number']))
                obj.full_clean(); obj.save(); messages.success(request,'Lecture assignment added.')
            elif action == 'edit':
                obj=WeeklySchedule.objects.filter(pk=int(request.POST['id']), class_subject__class_groups__term=active).distinct().get()
                obj.weekday=int(request.POST['weekday']); obj.lecture_number=int(request.POST['lecture_number'])
                obj.full_clean(); obj.save(); messages.success(request,'Lecture assignment updated.')
            elif action == 'delete':
                obj=WeeklySchedule.objects.filter(pk=int(request.POST['id']), class_subject__class_groups__term=active).distinct().get()
                obj.delete(); messages.success(request,'Lecture assignment removed.')
            else: raise ValueError('Unknown action.')
            return redirect('lecture_schedule_manage')
        except (ValueError, KeyError, ValidationError, IntegrityError, ClassSubject.DoesNotExist, WeeklySchedule.DoesNotExist) as exc:
            messages.error(request,f'Could not save lecture assignment: {exc}')

    offerings=ClassSubject.objects.filter(class_groups__term=active).select_related('subject','lecturer','class_group').prefetch_related('class_groups', 'weekly_schedules').distinct().order_by('subject__code') if active else ClassSubject.objects.none()
    schedules=WeeklySchedule.objects.filter(class_subject__class_groups__term=active).select_related('class_subject__subject','class_subject__lecturer').prefetch_related('class_subject__class_groups').distinct().order_by('weekday','lecture_number','class_subject__subject__code') if active else WeeklySchedule.objects.none()
    offerings = list(offerings)
    schedules = list(schedules)
    by_offering = {}
    readiness = {'total': len(offerings), 'ready': 0, 'missing_teacher': 0, 'inactive_teacher': 0, 'missing_schedule': 0}
    for schedule in schedules:
        by_offering.setdefault(schedule.class_subject_id, []).append(schedule)
    for offering in offerings:
        offering.display_schedules = by_offering.get(offering.pk, [])
        offering.missing_teacher = not offering.lecturer_id
        offering.inactive_teacher = bool(offering.lecturer_id and not offering.lecturer.is_active)
        offering.missing_schedule = not offering.display_schedules
        offering.is_ready = not (offering.missing_teacher or offering.inactive_teacher or offering.missing_schedule)
        if offering.is_ready:
            readiness['ready'] += 1
        for key in ('missing_teacher', 'inactive_teacher', 'missing_schedule'):
            readiness[key] += bool(getattr(offering, key))

    conflicts = []
    for index, first in enumerate(schedules):
        for second in schedules[index + 1:]:
            if (first.weekday, first.lecture_number) != (second.weekday, second.lecture_number):
                continue
            same_teacher = bool(first.class_subject.lecturer_id and first.class_subject.lecturer_id == second.class_subject.lecturer_id)
            overlap = bool(set(first.class_subject.linked_class_ids()) & set(second.class_subject.linked_class_ids()))
            if same_teacher or overlap:
                conflicts.append({'first': first, 'second': second, 'reason': 'Teacher clash' if same_teacher else 'Class clash'})

    conflicted_ids = {
        pk for item in conflicts
        for pk in (item['first'].class_subject_id, item['second'].class_subject_id)
    }
    for offering in offerings:
        offering.has_conflict = offering.pk in conflicted_ids
        if offering.has_conflict and offering.is_ready:
            offering.is_ready = False
            readiness['ready'] -= 1
    readiness['conflict_sections'] = len(conflicted_ids)

    return render(request, 'academics/lecture_schedule.html', {
        'active_term': active, 'offerings': offerings, 'schedules': schedules,
        'days': WeeklySchedule.DAYS, 'readiness': readiness, 'conflicts': conflicts,
    })

@role_required('ADMIN')
@require_http_methods(['GET','POST'])
def attendance_settings_manage(request):
    policy,_=AttendanceSettings.objects.get_or_create(pk=1)
    if request.method == 'POST':
        try:
            from datetime import time
            policy.working_start=time.fromisoformat(request.POST['working_start'])
            policy.working_end=time.fromisoformat(request.POST['working_end'])
            policy.full_clean(); policy.save(); messages.success(request,'Attendance working hours updated.')
            return redirect('attendance_settings_manage')
        except (ValueError, KeyError, ValidationError) as exc:
            messages.error(request,f'Could not save attendance settings: {exc}')
    return render(request,'settings/attendance.html',{'hours':policy})


@role_required('ADMIN')
@require_http_methods(['GET','POST'])
def fine_settings_manage(request):
    active=AcademicTerm.objects.filter(is_active=True).first()
    policy=FinePolicy.objects.filter(term=active).first() if active else None
    if request.method == 'POST':
        try:
            if not active: raise ValueError('Create or activate a term first.')
            allowed=int(request.POST['allowed_absences'])
            rate=Decimal(request.POST['rate_per_extra_absence'])
            if allowed < 0 or rate < 0: raise ValueError('Fine settings cannot be negative.')
            with transaction.atomic():
                policy,_=FinePolicy.objects.update_or_create(term=active, defaults={'allowed_absences':allowed,'rate_per_extra_absence':rate})
                for group in ClassGroup.objects.filter(term=active):
                    students=StudentProfile.objects.filter(memberships__class_group=group)
                    offerings=ClassSubject.objects.filter(class_groups=group).distinct()
                    for student in students:
                        locked=StudentProfile.objects.select_for_update().get(pk=student.pk)
                        for offering in offerings:
                            reconcile_fine(locked, offering, actor=request.user)
            messages.success(request,'Fine policy saved and outstanding balances reconciled.')
            return redirect('fine_settings_manage')
        except (ValueError, KeyError, InvalidOperation) as exc:
            messages.error(request,f'Could not save fine settings: {exc}')
    return render(request,'settings/fines.html',{'active_term':active,'fine_policy':policy})


@role_required('ADMIN')
@require_http_methods(['GET', 'POST'])
def branding_settings_manage(request):
    if not request.user.is_superuser:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('Only the Super Admin can change application branding.')

    branding, _ = AppBranding.objects.get_or_create(
        pk=1,
        defaults={
            'app_name': 'Clasvanta',
            'subtitle': 'Academic Attendance & Management',
        },
    )
    if request.method == 'POST':
        branding.app_name = request.POST.get('app_name', '').strip()
        branding.subtitle = request.POST.get('subtitle', '').strip()
        branding.updated_by = request.user
        try:
            branding.full_clean()
            branding.save()
            messages.success(request, 'Application branding updated.')
            return redirect('branding_settings_manage')
        except ValidationError as exc:
            messages.error(request, f'Could not save branding: {exc}')

    return render(request, 'settings/branding.html', {'branding': branding})
