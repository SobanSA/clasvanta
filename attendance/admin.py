from django.contrib import admin
from .models import AttendanceSettings, MakeupClass, LectureSession, AttendanceRecord, AttendanceAudit, SessionDeletionAudit


@admin.register(AttendanceSettings)
class SettingsAdmin(admin.ModelAdmin):
    list_display = ('working_start', 'working_end')
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LectureSession)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('lecture_date', 'lecture_number', 'class_subject', 'status', 'submitted_by')
    def has_add_permission(self, request):
        return False  # Use audited custom admin workflow.
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AttendanceRecord)
class RecordAdmin(admin.ModelAdmin):
    list_display = ('session', 'student', 'status')
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AttendanceAudit)
class AuditAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'actor_role', 'action', 'student', 'session', 'old_status', 'new_status')
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MakeupClass)
class MakeupClassAdmin(admin.ModelAdmin):
    list_display = ('lecture_date', 'lecture_number', 'class_subject', 'status', 'requested_by', 'reviewed_by')
    list_filter = ('status', 'lecture_date')
    search_fields = ('class_subject__subject__name', 'class_subject__subject__code', 'requested_by__username')
    def has_add_permission(self, request):
        return False  # Use the custom approval workflow.
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SessionDeletionAudit)
class SessionDeletionAuditAdmin(admin.ModelAdmin):
    list_display = ('deleted_at', 'lecture_date', 'lecture_number', 'class_subject', 'record_count', 'deleted_by')
    list_filter = ('lecture_date', 'deleted_at')
    search_fields = ('class_subject__subject__name', 'class_subject__subject__code', 'deleted_by__username', 'reason')
    readonly_fields = [field.name for field in SessionDeletionAudit._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
