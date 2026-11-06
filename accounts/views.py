from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods


def role_required(*roles):
    def deco(func):
        @login_required
        @wraps(func)
        def wrapped(request, *args, **kwargs):
            user = request.user
            if user.must_change_password:
                return redirect('password_change')
            if not (user.is_superuser or user.role in roles):
                raise PermissionDenied('You cannot access this page.')
            return func(request, *args, **kwargs)
        return wrapped
    return deco


@login_required
def dashboard(request):
    if request.user.must_change_password:
        return redirect('password_change')
    if request.user.is_superuser or request.user.role == 'ADMIN':
        from academics.views import admin_dashboard
        return admin_dashboard(request)
    if request.user.role == 'LECTURER':
        from attendance.views import lecturer_dashboard
        return lecturer_dashboard(request)
    from academics.views import student_dashboard
    return student_dashboard(request)


@login_required
@require_http_methods(['GET', 'POST'])
def change_password(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        user.must_change_password = False
        user.save(update_fields=['must_change_password'])
        update_session_auth_hash(request, user)
        messages.success(request, 'Password updated.')
        return redirect('dashboard')
    return render(request, 'accounts/change_password.html', {'form': form})
