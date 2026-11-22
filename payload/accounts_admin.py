from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group

from .models import User


@admin.register(User)
class AttendanceUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Clasvanta access', {'fields': ('role',)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Clasvanta access', {
            'fields': ('first_name', 'last_name', 'role', 'is_active', 'groups'),
            'description': (
                'For Accounts staff, choose the Accounts group. '
                'Clasvanta will synchronize the application role automatically.'
            ),
        }),
    )
    list_display = (
        'username', 'first_name', 'last_name', 'role',
        'is_staff', 'is_active',
    )
    list_filter = ('role', 'groups', 'is_staff', 'is_active')

    def save_model(self, request, obj, form, change):
        if obj.role == User.Role.ACCOUNTS:
            obj.is_staff = False
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        user = form.instance
        accounts_group, _ = Group.objects.get_or_create(name='Accounts')
        in_accounts_group = user.groups.filter(pk=accounts_group.pk).exists()

        if in_accounts_group and user.role != User.Role.ACCOUNTS:
            User.objects.filter(pk=user.pk).update(
                role=User.Role.ACCOUNTS,
                is_staff=False,
            )
            user.role = User.Role.ACCOUNTS
            user.is_staff = False
        elif user.role == User.Role.ACCOUNTS and not in_accounts_group:
            user.groups.add(accounts_group)
            if user.is_staff:
                User.objects.filter(pk=user.pk).update(is_staff=False)
                user.is_staff = False
