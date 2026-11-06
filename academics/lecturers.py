"""Admin-facing lecturer directory and account lifecycle (no student data changes)."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from accounts.models import User
from accounts.views import role_required
from .imports import _password
from .models import AcademicTerm, ClassSubject


@never_cache
@role_required('ADMIN')
@require_http_methods(['GET', 'POST'])
def lecturers_manage(request):
    """Lecturer username is the teacher ID (already used by academic CSV imports)."""
    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            with transaction.atomic():
                if action == 'create':
                    teacher_id = request.POST.get('teacher_id', '').strip()
                    name = request.POST.get('name', '').strip()
                    if not teacher_id or not name:
                        raise ValidationError('Teacher ID and name are required.')
                    if User.objects.filter(username__iexact=teacher_id).exists():
                        raise ValidationError('That teacher ID already belongs to a user.')
                    password = _password()
                    teacher = User(username=teacher_id, first_name=name,
                                   role='LECTURER', is_active=True, must_change_password=True)
                    teacher.set_password(password)
                    teacher.full_clean()
                    teacher.save()
                    request.session['lecturer_once_password'] = {
                        'teacher_id': teacher.username, 'name': name, 'password': password,
                    }
                    messages.success(request, 'Lecturer created. Copy the one-time credentials now.')
                elif action in ('reset_password', 'set_active', 'update'):
                    teacher = get_object_or_404(User.objects.select_for_update(),
                                                pk=int(request.POST['lecturer_id']), role='LECTURER')
                    if action == 'reset_password':
                        password = _password()
                        teacher.set_password(password)
                        teacher.must_change_password = True
                        teacher.save(update_fields=['password', 'must_change_password'])
                        request.session['lecturer_once_password'] = {
                            'teacher_id': teacher.username,
                            'name': teacher.get_full_name() or teacher.first_name,
                            'password': password,
                        }
                        messages.success(request, 'New temporary password created. Copy it now.')
                    elif action == 'set_active':
                        teacher.is_active = request.POST.get('is_active') == '1'
                        teacher.save(update_fields=['is_active'])
                        messages.success(request, 'Lecturer status updated.')
                    else:
                        name = request.POST.get('name', '').strip()
                        if not name:
                            raise ValidationError('Teacher name is required.')
                        teacher.first_name, teacher.last_name = name, ''
                        teacher.full_clean()
                        teacher.save(update_fields=['first_name', 'last_name'])
                        messages.success(request, 'Lecturer name updated.')
                else:
                    raise ValidationError('Unknown lecturer action.')
            return redirect('lecturers_manage')
        except (ValueError, ValidationError, IntegrityError) as exc:
            messages.error(request, f'Could not update lecturer: {exc}')

    active = AcademicTerm.objects.filter(is_active=True).first()
    search = request.GET.get('q', '').strip()[:80]
    teachers = User.objects.filter(role='LECTURER').order_by('first_name', 'username')
    if search:
        teachers = teachers.filter(Q(username__icontains=search) | Q(first_name__icontains=search) |
                                   Q(last_name__icontains=search))
    teacher_rows = []
    assignments = ClassSubject.objects.select_related('subject', 'lecturer', 'class_group__term').prefetch_related(
        'class_groups', 'weekly_schedules'
    ).filter(class_group__term=active) if active else ClassSubject.objects.none()
    by_teacher = {}
    for offering in assignments:
        by_teacher.setdefault(offering.lecturer_id, []).append(offering)
    for teacher in teachers:
        sections = by_teacher.get(teacher.pk, [])
        teacher_rows.append({'teacher': teacher, 'sections': sections,
                             'section_count': len(sections),
                             'merged_count': sum(section.class_count > 1 for section in sections)})
    return render(request, 'academics/lecturers.html', {
        'rows': teacher_rows, 'search': search, 'active_term': active,
        'total': User.objects.filter(role='LECTURER').count(),
        'active_count': User.objects.filter(role='LECTURER', is_active=True).count(),
        'credentials': request.session.pop('lecturer_once_password', None),
    })
