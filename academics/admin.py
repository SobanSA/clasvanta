from django import forms
from django.contrib import admin
from .contact_forms import WhatsAppNumberField
from .models import Programme, AcademicTerm, ClassGroup, Subject, StudentProfile, ClassMembership, ClassSubject, WeeklySchedule

admin.site.register(Programme)
admin.site.register(AcademicTerm)
admin.site.register(ClassGroup)
admin.site.register(Subject)
admin.site.register(ClassMembership)


class StudentProfileAdminForm(forms.ModelForm):
    whatsapp_number = WhatsAppNumberField(required=False)

    class Meta:
        model = StudentProfile
        fields = '__all__'


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    form = StudentProfileAdminForm
    list_display = ('user', 'father_name', 'whatsapp_number', 'contact_complete')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'father_name', 'whatsapp_number')
    list_select_related = ('user',)

    @admin.display(boolean=True, description='Contact details complete')
    def contact_complete(self, obj):
        return obj.contact_details_complete


@admin.register(ClassSubject)
class ClassSubjectAdmin(admin.ModelAdmin):
    list_display = ('subject', 'section_code', 'lecturer', 'linked_classes')
    list_filter = ('class_groups__term', 'class_groups__programme')
    search_fields = ('class_groups__code', 'subject__code', 'subject__name', 'section_code', 'lecturer__username', 'lecturer__first_name')
    filter_horizontal = ('class_groups',)

    @admin.display(description='Classes')
    def linked_classes(self, obj):
        return obj.class_codes_display


@admin.register(WeeklySchedule)
class WeeklyScheduleAdmin(admin.ModelAdmin):
    list_display = ('class_subject', 'weekday', 'lecture_number')
    list_filter = ('weekday',)
