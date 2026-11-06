from django.contrib import admin
from .models import FinePolicy, FineLedgerEntry


@admin.register(FinePolicy)
class FinePolicyAdmin(admin.ModelAdmin):
    list_display = ('term', 'allowed_absences', 'rate_per_extra_absence')
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FineLedgerEntry)
class FineLedgerAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'student', 'class_subject', 'kind', 'amount', 'actor')
    def has_add_permission(self, request):
        return False  # Only app service can add ledger entries.
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False
