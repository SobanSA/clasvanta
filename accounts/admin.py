from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class AttendanceUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Attendance System', {'fields': ('role',)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Attendance System', {'fields': ('role',)}),
    )
    list_display = ('username', 'first_name', 'last_name', 'role', 'is_staff', 'is_active')
    list_filter = ('role', 'is_staff', 'is_active')
