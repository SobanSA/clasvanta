from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView
from accounts import views as account_views
from academics import views as academic_views
from academics import lecturers as lecturer_admin_views
from academics import student_portal as student_portal_views
from academics import reports as report_views
from attendance import views as attendance_views
from fines import views as fine_views

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='dashboard', permanent=False), name='home'),
    path('login/', auth_views.LoginView.as_view(template_name='accounts/login.html', redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('dashboard/', account_views.dashboard, name='dashboard'),
    path('password/change/', account_views.change_password, name='password_change'),
    path('setup/', academic_views.academic_setup, name='academic_setup'),
    path('structure/', academic_views.academic_structure, name='academic_structure'),
    path('students/', academic_views.students_list, name='students_list'),
    path('students/add/', academic_views.student_add, name='student_add'),
    path('students/attendance/', academic_views.student_attendance, name='student_attendance'),
    path('student/attendance/', student_portal_views.my_attendance, name='student_my_attendance'),
    path('student/schedule/', student_portal_views.my_schedule, name='student_schedule'),
    path('student/fines/', student_portal_views.my_fines, name='student_fines'),
    path('student/profile/', student_portal_views.profile, name='student_profile'),
    path('academic/programmes/', academic_views.programmes_manage, name='programmes_manage'),
    path('academic/terms/', academic_views.terms_manage, name='terms_manage'),
    path('academic/classes/', academic_views.classes_manage, name='classes_manage'),
    path('academic/subjects/', academic_views.subjects_manage, name='subjects_manage'),
    path('lecturers/', lecturer_admin_views.lecturers_manage, name='lecturers_manage'),
    path('academic/teacher-assignments/', academic_views.teacher_assignments, name='teacher_assignments'),
    path('academic/lecture-schedule/', academic_views.lecture_schedule_manage, name='lecture_schedule_manage'),
    path('settings/attendance/', academic_views.attendance_settings_manage, name='attendance_settings_manage'),
    path('settings/fines/', academic_views.fine_settings_manage, name='fine_settings_manage'),
    path('settings/branding/', academic_views.branding_settings_manage, name='branding_settings_manage'),
    path('imports/<str:kind>/', academic_views.bulk_import, name='bulk_import'),
    path('lectures/', attendance_views.lecturer_dashboard, name='lecturer_dashboard'),
    path('lectures/history/', attendance_views.lecturer_history, name='lecturer_history'),
    path('attendance/schedule/<int:pk>/', attendance_views.mark_schedule, name='mark_schedule'),
    path('attendance/makeup/<int:pk>/', attendance_views.mark_makeup, name='mark_makeup'),
    path('attendance/cancel/', attendance_views.cancel_occurrence, name='cancel_occurrence'),
    path('attendance/session/<int:pk>/', attendance_views.session_detail, name='session_detail'),
    path('attendance/session/<int:pk>/delete/', attendance_views.delete_session, name='delete_session'),
    path('attendance/manage/', attendance_views.admin_sessions, name='admin_sessions'),
    path('attendance/make-up/', attendance_views.makeup_classes, name='makeup_classes'),
    path('attendance/manage/new/', attendance_views.admin_new_session, name='admin_new_session'),
    path('attendance/log/', attendance_views.audit_log, name='audit_log'),
    path('fines/', fine_views.fines_dashboard, name='fines_dashboard'),
    path('reports/', report_views.reports, name='reports'),
    path('admin/', admin.site.urls),
]
