"""Staff-only student directory, academic profile and temporary password resets."""
import re
from decimal import Decimal

from django import forms
from django.core import signing
from django.contrib.auth.hashers import check_password
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils.crypto import salted_hmac
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_http_methods

from accounts.models import User
from accounts.views import role_required
from attendance.models import AttendanceRecord
from fines.models import FineLedgerEntry

from .imports import _password
from .models import ClassMembership, StudentProfile
from .student_portal import _assigned_offerings
from .workload import weekly_workload_for_offerings


SEARCH_LIMIT = 30
RESET_SALT = 'clasvanta.student-password-reset.v1'
RESET_MAX_AGE = 600
ZERO = Decimal('0.00')


class StudentSearchForm(forms.Form):
    q = forms.CharField(
        label='Find a student', max_length=160, required=True,
        widget=forms.TextInput(attrs={
            'type': 'search', 'placeholder': 'Name, registration, father name or WhatsApp…',
            'autocomplete': 'off', 'enterkeyhint': 'search',
        }),
    )


def _students():
    """Exclude any profile attached to a non-student or privileged user."""
    return StudentProfile.objects.filter(
        user__role=User.Role.STUDENT, user__is_superuser=False, user__is_staff=False,
    ).select_related('user')


def _matching_students(query):
    # Each name/registration token may match a different field. Keep phone
    # searches tolerant of spaces, separators, and Pakistani local format.
    parts = query.split()
    match = Q()
    for part in parts:
        match &= (
            Q(user__username__icontains=part) | Q(user__first_name__icontains=part)
            | Q(user__last_name__icontains=part) | Q(father_name__icontains=part)
            | Q(whatsapp_number__icontains=part)
        )
    if re.fullmatch(r'[+0-9 ()\-]+', query):
        digits = re.sub(r'[^0-9]', '', query)
        if digits:
            phone = digits
            if digits.startswith('00'):
                phone = digits[2:]
            elif digits.startswith('03'):
                phone = '92' + digits[1:]
            if phone:
                match |= Q(whatsapp_number__icontains=phone)
    return _students().filter(match).order_by('user__username', 'pk')


@never_cache
@role_required('ADMIN', 'ACCOUNTS')
@csrf_protect
@require_http_methods(['GET', 'POST'])
def student_profiles(request):
    """Search all student accounts, including inactive and past-term students.

    Use a POST search so contact numbers do not appear in query-string history
    or routine URL access logs. Do not render the full student roster at rest.
    """
    form = StudentSearchForm(request.POST if request.method == 'POST' else None)
    results = []
    searched = False
    truncated = False
    if request.method == 'POST' and form.is_valid():
        searched = True
        results = list(_matching_students(form.cleaned_data['q'])[:SEARCH_LIMIT + 1])
        truncated = len(results) > SEARCH_LIMIT
        results = results[:SEARCH_LIMIT]
    return render(request, 'academics/student_profiles.html', {
        'search_form': form, 'results': results, 'searched': searched,
        'truncated': truncated, 'search_limit': SEARCH_LIMIT,
    })


@never_cache
@role_required('ADMIN', 'ACCOUNTS')
@require_GET
def student_profile_detail(request, student_id):
    student = get_object_or_404(_students(), pk=student_id)
    memberships = list(ClassMembership.objects.filter(student=student)
                       .select_related('term', 'class_group__programme')
                       .order_by('-term__start_date', '-pk'))
    membership = next((item for item in memberships if item.term.is_active), None)
    offerings = _assigned_offerings(membership)
    offering_ids = [offering.pk for offering in offerings]
    weekly = weekly_workload_for_offerings(offerings)

    # Same Held-only, assigned-offering scope as the student portal. Aggregate
    # without creating a FinePolicy or any other row during a staff GET.
    attendance = AttendanceRecord.objects.filter(
        student=student, session__status='SUBMITTED',
        session__class_subject_id__in=offering_ids,
    ).order_by().values('session__class_subject_id').annotate(
        total=Count('pk'), present=Count('pk', filter=Q(status=AttendanceRecord.PRESENT)),
    )
    counts = {row['session__class_subject_id']: row for row in attendance}
    subjects = []
    total = present = 0
    for offering in offerings:
        count = counts.get(offering.pk, {'total': 0, 'present': 0})
        total += count['total']
        present += count['present']
        subjects.append({'offering': offering, 'total': count['total'], 'present': count['present']})

    # Fine dashboard semantics: sum positive balances separately by subject
    # section across all terms; a credit in one section cannot hide another debt.
    balances = FineLedgerEntry.objects.filter(student=student).order_by().values(
        'class_subject_id',
    ).annotate(balance=Sum('amount'))
    outstanding = sum((max(ZERO, row['balance'] or ZERO) for row in balances), ZERO)

    return render(request, 'academics/student_profile_detail.html', {
        'student': student, 'membership': membership, 'memberships': memberships,
        'subjects': subjects, 'weekly': weekly, 'search_form': StudentSearchForm(),
        'summary': {'total': total, 'present': present, 'absent': total - present,
                    'percentage': round(100 * present / total, 1) if total else None,
                    'subject_count': len(offerings), 'outstanding': outstanding},
    })


def _reset_payload(actor, student, target):
    # A signed, short-lived confirmation is tied to the actor, target identity,
    # and current password hash. Never expose the actual hash in the form.
    fingerprint = salted_hmac(RESET_SALT, target.password + '\0' + target.username,
                              algorithm='sha256').hexdigest()
    return {'actor': actor.pk, 'student': student.pk, 'target': target.pk, 'state': fingerprint}


def _reset_page(request, student, *, error=None, status=200):
    token = signing.dumps(_reset_payload(request.user, student, student.user), salt=RESET_SALT)
    return render(request, 'academics/student_reset_password.html', {
        'student': student, 'confirmation_token': token, 'reset_error': error,
    }, status=status)


@never_cache
@role_required('ADMIN')
@csrf_protect
@require_http_methods(['GET', 'POST'])
def student_reset_password(request, student_id):
    """Reset a genuine student account; never accept a password or target from POST.

    The temporary password exists only in the successful response, not in a
    session, redirect URL, message, or log. A replay/refresh of that POST fails
    because the original confirmation token no longer matches the password hash.
    """
    student = get_object_or_404(_students(), pk=student_id)
    if request.method == 'GET':
        return _reset_page(request, student)

    if request.POST.get('confirm') != 'yes':
        return _reset_page(request, student, error='Confirm the reset before continuing.', status=400)
    try:
        token = request.POST.get('confirmation_token', '')
        payload = signing.loads(token, salt=RESET_SALT, max_age=RESET_MAX_AGE)
    except signing.BadSignature:
        return _reset_page(request, student, error='This confirmation expired or is invalid. Please confirm again.', status=409)

    with transaction.atomic():
        # Lock in the same profile-then-user order as existing identity edits.
        student = get_object_or_404(StudentProfile.objects.select_for_update(), pk=student_id)
        target = get_object_or_404(User.objects.select_for_update(), pk=student.user_id,
                                   role=User.Role.STUDENT, is_superuser=False, is_staff=False)
        student.user = target
        if payload != _reset_payload(request.user, student, target):
            return _reset_page(request, student, error='This confirmation was already used or the account changed. Please confirm again.', status=409)
        temporary = _password()
        while check_password(temporary, target.password):
            temporary = _password()
        target.set_password(temporary)
        target.must_change_password = True
        target.save(update_fields=['password', 'must_change_password'])

    return render(request, 'academics/student_reset_password.html', {
        'student': student, 'temporary_password': temporary,
    })
