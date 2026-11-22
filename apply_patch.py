#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
import py_compile
import re
import shutil
import sys

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PAYLOAD = HERE / "payload"

required = [
    ROOT / "manage.py",
    ROOT / "accounts/models.py",
    ROOT / "accounts/views.py",
    ROOT / "accounts/admin.py",
    ROOT / "academics/models.py",
    ROOT / "academics/views.py",
    ROOT / "fines/models.py",
    ROOT / "fines/services.py",
    ROOT / "fines/views.py",
    ROOT / "config/urls.py",
    ROOT / "templates/base.html",
    ROOT / "templates/academics/students_list.html",
    ROOT / "templates/academics/student_add.html",
    ROOT / "templates/academics/student_attendance.html",
]
for path in required:
    if not path.exists():
        sys.exit("ERROR: missing required file: " + str(path.relative_to(ROOT)))
if not PAYLOAD.exists():
    sys.exit("ERROR: payload folder is missing. Upload the whole extracted patch folder.")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = ROOT / (".accounts_permissions_v287_backup_" + stamp)
backup_dir.mkdir()

def backup(path):
    if path.exists():
        dst = backup_dir / path.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(label + ": expected 1 matching block, found " + str(count))
    return text.replace(old, new, 1)

def read_payload(name):
    return (PAYLOAD / name).read_text(encoding="utf-8")

for p in required:
    backup(p)

try:
    # accounts/models.py
    path = ROOT / "accounts/models.py"
    text = path.read_text(encoding="utf-8")
    if "ACCOUNTS = 'ACCOUNTS', 'Accounts'" not in text:
        old = "        ADMIN = 'ADMIN', 'Administrator'\n        LECTURER = 'LECTURER', 'Lecturer'\n        STUDENT = 'STUDENT', 'Student'\n"
        new = "        ADMIN = 'ADMIN', 'Administrator'\n        ACCOUNTS = 'ACCOUNTS', 'Accounts'\n        LECTURER = 'LECTURER', 'Lecturer'\n        STUDENT = 'STUDENT', 'Student'\n"
        text = replace_once(text, old, new, "accounts/models.py role choices")
    path.write_text(text, encoding="utf-8")

    # accounts/admin.py
    path = ROOT / "accounts/admin.py"
    path.write_text(read_payload("accounts_admin.py"), encoding="utf-8")

    # accounts/views.py
    path = ROOT / "accounts/views.py"
    text = path.read_text(encoding="utf-8")
    if "request.user.role == 'ACCOUNTS'" not in text:
        old = "    if request.user.is_superuser or request.user.role == 'ADMIN':\n        from academics.views import admin_dashboard\n        return admin_dashboard(request)\n    if request.user.role == 'LECTURER':\n"
        new = "    if request.user.is_superuser or request.user.role == 'ADMIN':\n        from academics.views import admin_dashboard\n        return admin_dashboard(request)\n    if request.user.role == 'ACCOUNTS':\n        return redirect('students_list')\n    if request.user.role == 'LECTURER':\n"
        text = replace_once(text, old, new, "accounts/views.py Accounts dashboard")
    path.write_text(text, encoding="utf-8")

    # academics/models.py
    path = ROOT / "academics/models.py"
    text = path.read_text(encoding="utf-8")
    if "father_name = models.CharField(" not in text:
        old = "class StudentProfile(models.Model):\n    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='student_profile')\n"
        new = old + "    father_name = models.CharField(max_length=160, blank=True, default='')\n"
        text = replace_once(text, old, new, "academics/models.py father_name")
    path.write_text(text, encoding="utf-8")

    # academics/views.py
    path = ROOT / "academics/views.py"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"@role_required\('ADMIN'\)\n(def students_list\(request\):)", r"@role_required('ADMIN','ACCOUNTS')\n\1", text, count=1)
    text = re.sub(r"@role_required\('ADMIN'\)\n(def student_attendance\(request\):)", r"@role_required('ADMIN','ACCOUNTS')\n\1", text, count=1)
    text = re.sub(r"@role_required\('ADMIN'\)\n(@require_http_methods\(\['GET','POST'\]\)\ndef student_add\(request\):)", r"@role_required('ADMIN','ACCOUNTS')\n\1", text, count=1)
    if "father_name = request.POST.get('father_name'" not in text:
        text = replace_once(
            text,
            "            name = request.POST['student_name'].strip()\n            group = ClassGroup.objects.get(pk=int(request.POST['class_group']), term=active)\n",
            "            name = request.POST['student_name'].strip()\n            father_name = request.POST.get('father_name', '').strip()\n            group = ClassGroup.objects.get(pk=int(request.POST['class_group']), term=active)\n",
            "academics/views.py student_add father input",
        )
        text = replace_once(
            text,
            "                profile = StudentProfile.objects.create(user=user)\n",
            "                profile = StudentProfile.objects.create(user=user, father_name=father_name)\n",
            "academics/views.py student_add father save",
        )
        text = replace_once(
            text,
            "                'student_name': name,\n                'class_code': group.code,\n",
            "                'student_name': name,\n                'father_name': father_name,\n                'class_code': group.code,\n",
            "academics/views.py new student message",
        )
    if "def student_edit(request, student_id):" not in text:
        marker = "\n@role_required('ADMIN','ACCOUNTS')\ndef student_attendance(request):"
        if marker not in text:
            raise RuntimeError("academics/views.py student_attendance insertion point not found")
        text = text.replace(marker, "\n" + read_payload("student_edit_view.pyfrag").rstrip() + "\n\n@role_required('ADMIN','ACCOUNTS')\ndef student_attendance(request):", 1)
    path.write_text(text, encoding="utf-8")

    # fines/models.py
    path = ROOT / "fines/models.py"
    text = path.read_text(encoding="utf-8")
    if "('CONCESSION', 'Concession')" not in text:
        old = "    KINDS = [('CHARGE', 'Fine charge'), ('ADJUSTMENT', 'Fine adjustment'), ('PAYMENT', 'Payment')]\n"
        new = "    KINDS = [\n        ('CHARGE', 'Fine charge'),\n        ('ADJUSTMENT', 'Fine adjustment'),\n        ('PAYMENT', 'Payment'),\n        ('CONCESSION', 'Concession'),\n        ('WAIVER', 'Waiver'),\n        ('RELIEF_REVERSAL', 'Relief reversal'),\n    ]\n"
        text = replace_once(text, old, new, "fines/models.py kinds")
        text = replace_once(text, "    kind = models.CharField(max_length=12, choices=KINDS)\n", "    kind = models.CharField(max_length=18, choices=KINDS)\n", "fines/models.py kind length")
    path.write_text(text, encoding="utf-8")

    # fines/services.py
    path = ROOT / "fines/services.py"
    text = path.read_text(encoding="utf-8")
    if "Automatic relief normalization" not in text:
        marker = "\n\ndef subject_balance(student, offering):"
        if marker not in text:
            raise RuntimeError("fines/services.py subject_balance marker not found")
        text = text.replace(marker, "\n" + read_payload("relief_normalizer.pyfrag").rstrip() + marker, 1)
    path.write_text(text, encoding="utf-8")

    # fines/views.py
    path = ROOT / "fines/views.py"
    text = path.read_text(encoding="utf-8")
    if "from django.core.exceptions import PermissionDenied" not in text:
        text = text.replace("from django.contrib import messages\n", "from django.contrib import messages\nfrom django.core.exceptions import PermissionDenied\n", 1)

    start = text.find("@role_required('ADMIN')\n@require_http_methods(['GET', 'POST'])\ndef fines_dashboard")
    if start < 0:
        start = text.find("@role_required('ADMIN','ACCOUNTS')\n@require_http_methods(['GET', 'POST'])\ndef fines_dashboard")
    if start < 0:
        raise RuntimeError("fines/views.py fines_dashboard start not found")
    end = text.find("\n\n@role_required(", start + 10)
    if end < 0:
        raise RuntimeError("fines/views.py fines_dashboard end not found")
    text = text[:start] + read_payload("fines_dashboard_view.pyfrag").rstrip() + text[end:]

    if "def fine_student_detail(request, student_id):" not in text:
        marker = "\n@role_required('ADMIN')\n@require_GET\ndef fine_challan"
        if marker not in text:
            marker = "\n@role_required('ADMIN','ACCOUNTS')\n@require_GET\ndef fine_challan"
        if marker not in text:
            raise RuntimeError("fines/views.py fine_challan insertion point not found")
        text = text.replace(marker, "\n" + read_payload("fine_detail_view.pyfrag").rstrip() + "\n\n@role_required('ADMIN','ACCOUNTS')\n@require_GET\ndef fine_challan", 1)
    text = text.replace("@role_required('ADMIN')\n@require_GET\ndef fine_challan", "@role_required('ADMIN','ACCOUNTS')\n@require_GET\ndef fine_challan", 1)
    path.write_text(text, encoding="utf-8")

    # config/urls.py
    path = ROOT / "config/urls.py"
    text = path.read_text(encoding="utf-8")
    if "name='student_edit'" not in text:
        text = replace_once(text, "    path('students/add/', academic_views.student_add, name='student_add'),\n", "    path('students/add/', academic_views.student_add, name='student_add'),\n    path('students/<int:student_id>/edit/', academic_views.student_edit, name='student_edit'),\n", "config/urls.py student_edit")
    if "name='fine_student_detail'" not in text:
        text = replace_once(text, "    path('fines/', fine_views.fines_dashboard, name='fines_dashboard'),\n", "    path('fines/', fine_views.fines_dashboard, name='fines_dashboard'),\n    path('fines/student/<int:student_id>/', fine_views.fine_student_detail, name='fine_student_detail'),\n", "config/urls.py fine student detail")
    path.write_text(text, encoding="utf-8")

    # templates/base.html
    path = ROOT / "templates/base.html"
    text = path.read_text(encoding="utf-8")
    if "{% elif user.role == 'ACCOUNTS' %}" not in text:
        text = replace_once(text, "   {% elif user.role == 'LECTURER' %}\n", read_payload("accounts_nav.htmlfrag") + "   {% elif user.role == 'LECTURER' %}\n", "templates/base.html Accounts nav")
    path.write_text(text, encoding="utf-8")

    # student_add.html
    path = ROOT / "templates/academics/student_add.html"
    text = path.read_text(encoding="utf-8")
    if 'name="father_name"' not in text:
        text = replace_once(text, '<label>Student name</label><input name="student_name" placeholder="Student full name" required><label>Class</label>', '<label>Student name</label><input name="student_name" placeholder="Student full name" required><label>Father name <span class="muted">(optional)</span></label><input name="father_name" placeholder="Father name"><label>Class</label>', "student_add.html father field")
    text = text.replace("{{ new_student.registration_number }} · {{ new_student.student_name }} · {{ new_student.class_code }}", "{{ new_student.registration_number }} · {{ new_student.student_name }}{% if new_student.father_name %} · Father: {{ new_student.father_name }}{% endif %} · {{ new_student.class_code }}")
    path.write_text(text, encoding="utf-8")

    # student_attendance.html
    path = ROOT / "templates/academics/student_attendance.html"
    text = path.read_text(encoding="utf-8")
    text = text.replace("Search by registration number or name.", "Search by registration number, student name or father name.")
    text = text.replace("Search by registration number or student name.", "Search by registration number, student name or father name.")
    text = text.replace('placeholder="Start typing registration number or name…"', 'placeholder="Start typing registration number, student or father name…"')
    if "{{ m.student.father_name }}" not in text:
        text = replace_once(text, 'data-search="{{ m.student.user.username }} {{ m.student.user.get_full_name|default:m.student.user.first_name }} {{ m.class_group.code }}"', 'data-search="{{ m.student.user.username }} {{ m.student.user.get_full_name|default:m.student.user.first_name }} {{ m.student.father_name }} {{ m.class_group.code }}"', "student attendance search")
        text = replace_once(text, '<span>{{ m.student.user.username }} · {{ m.class_group.code }} · {{ m.class_group.programme.code }}</span>', '<span>{{ m.student.user.username }}{% if m.student.father_name %} · Father: {{ m.student.father_name }}{% endif %} · {{ m.class_group.code }} · {{ m.class_group.programme.code }}</span>', "student attendance display")
    path.write_text(text, encoding="utf-8")

    # students_list.html
    path = ROOT / "templates/academics/students_list.html"
    text = path.read_text(encoding="utf-8")
    text = text.replace('placeholder="Registration number or student name…"', 'placeholder="Registration number, student or father name…"')
    text = text.replace("Searches the students currently shown by the programme/class filters.", "Search by registration number, student name or father name within the current programme/class filters.")
    import_link = '<a class="btn btn-secondary" href="{% url \'bulk_import\' \'students\' %}">⇧ Import students</a>'
    if import_link in text and "{% if user.is_superuser or user.role == 'ADMIN' %}" + import_link not in text:
        text = text.replace(import_link, "{% if user.is_superuser or user.role == 'ADMIN' %}" + import_link + "{% endif %}", 1)

    if "<th>Father name</th>" not in text:
        text = replace_once(text, "<th>Student</th>", "<th>Student</th><th>Father name</th>", "students list father header")
    father_cell = '<td>{{ row.membership.student.father_name|default:"—" }}</td>'
    if father_cell not in text:
        text = replace_once(text, '<td>{{ row.membership.student.user.get_full_name|default:row.membership.student.user.first_name }}</td><td>{{ row.membership.class_group.programme.code }}</td>', '<td>{{ row.membership.student.user.get_full_name|default:row.membership.student.user.first_name }}</td>' + father_cell + '<td>{{ row.membership.class_group.programme.code }}</td>', "students list father cell")
    if "{{ row.membership.student.father_name }}" not in text:
        text = text.replace("{{ row.membership.student.user.get_full_name|default:row.membership.student.user.first_name }} {{ row.membership.class_group.programme.code }}", "{{ row.membership.student.user.get_full_name|default:row.membership.student.user.first_name }} {{ row.membership.student.father_name }} {{ row.membership.class_group.programme.code }}", 1)

    edit_link = '<a class="btn btn-small btn-secondary" href="{% url \'student_edit\' row.membership.student.pk %}">Edit</a>'
    v2 = '<td><div class="row-actions"><form method="post" action="{% url \'student_delete\' row.membership.student.pk %}" onsubmit="return confirm(\'{% if row.membership.student.user.is_active %}Deactivate this student account? The student will no longer be able to sign in.{% else %}Activate this student account?{% endif %}\');">{% csrf_token %}<input type="hidden" name="action" value="toggle_active"><input type="hidden" name="return_to" value="list"><button class="btn btn-small {% if row.membership.student.user.is_active %}btn-danger-soft{% else %}btn-primary{% endif %}" type="submit">{% if row.membership.student.user.is_active %}Deactivate{% else %}Activate{% endif %}</button></form><a class="btn btn-small btn-secondary" href="{% url \'student_delete\' row.membership.student.pk %}">Manage / Delete</a></div></td>'
    if v2 in text:
        new_v2 = '<td><div class="row-actions">' + edit_link + "{% if user.is_superuser or user.role == 'ADMIN' %}" + v2[len('<td><div class="row-actions">'):-len('</div></td>')] + "{% endif %}</div></td>"
        text = text.replace(v2, new_v2, 1)
    else:
        old_delete = '<td><div class="row-actions"><a class="btn btn-small btn-danger-soft" href="{% url \'student_delete\' row.membership.student.pk %}">Delete</a></div></td>'
        if old_delete in text:
            text = text.replace(old_delete, '<td><div class="row-actions">' + edit_link + "{% if user.is_superuser or user.role == 'ADMIN' %}<a class=\"btn btn-small btn-danger-soft\" href=\"{% url 'student_delete' row.membership.student.pk %}\">Delete</a>{% endif %}</div></td>", 1)
        elif "student_edit' row.membership.student.pk" not in text:
            text = replace_once(text, "<th>Account</th></tr>", "<th>Account</th><th>Actions</th></tr>", "students list actions header")
            stock = '<td>{% if row.membership.student.user.is_active %}<span class="status-pill done">Active</span>{% else %}<span class="status-pill">Disabled</span>{% endif %}</td></tr>'
            if stock not in text:
                stock = '<td>{% if row.membership.student.user.is_active %}<span class="status-pill done">Active</span>{% else %}<span class="status-pill">Inactive</span>{% endif %}</td></tr>'
            text = replace_once(text, stock, stock[:-5] + '<td><div class="row-actions">' + edit_link + '</div></td></tr>', "students list edit action")

    text = re.sub(r'colspan="(\d+)" class="empty-cell">(No enrolled students found[^<]*)', lambda m: 'colspan="' + str(int(m.group(1)) + 1) + '" class="empty-cell">' + m.group(2), text, count=1)
    text = re.sub(r'colspan="(\d+)" class="empty-cell">(No students match this search\.)', lambda m: 'colspan="' + str(int(m.group(1)) + 1) + '" class="empty-cell">' + m.group(2), text, count=1)
    path.write_text(text, encoding="utf-8")

    # Remove the incorrectly numbered migration produced by the first v2.8.7
    # package if this installer is being used as a repair/reinstall.
    wrong_accounts_migration = ROOT / "accounts/migrations/0002_accounts_role.py"
    if wrong_accounts_migration.exists():
        backup(wrong_accounts_migration)
        wrong_accounts_migration.unlink()

    # Write new/replacement templates and migrations.
    direct = {
        ROOT / "templates/academics/student_edit.html": "student_edit.html",
        ROOT / "templates/fines/dashboard.html": "fines_dashboard.html",
        ROOT / "templates/fines/student_detail.html": "fine_student_detail.html",
        ROOT / "accounts/migrations/0003_accounts_role.py": "0003_accounts_role.py",
        ROOT / "academics/migrations/0007_studentprofile_father_name.py": "0007_studentprofile_father_name.py",
        ROOT / "fines/migrations/0002_fineledgerentry_relief_kinds.py": "0002_fineledgerentry_relief_kinds.py",
    }
    for dst, src in direct.items():
        if dst.exists():
            backup(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(read_payload(src), encoding="utf-8")

    # Replace fines dashboard template last.
    path = ROOT / "templates/fines/dashboard.html"
    path.write_text(read_payload("fines_dashboard.html"), encoding="utf-8")

    # Python syntax validation.
    python_files = [
        ROOT / "accounts/models.py",
        ROOT / "accounts/views.py",
        ROOT / "accounts/admin.py",
        ROOT / "academics/models.py",
        ROOT / "academics/views.py",
        ROOT / "fines/models.py",
        ROOT / "fines/services.py",
        ROOT / "fines/views.py",
        ROOT / "config/urls.py",
        ROOT / "accounts/migrations/0003_accounts_role.py",
        ROOT / "academics/migrations/0007_studentprofile_father_name.py",
        ROOT / "fines/migrations/0002_fineledgerentry_relief_kinds.py",
    ]
    for py in python_files:
        py_compile.compile(str(py), doraise=True)

except Exception as exc:
    print("ERROR:", exc)
    print("A backup was created at:", backup_dir.name)
    print("No automatic rollback was attempted. Restore from that directory if needed.")
    sys.exit(1)

print("SUCCESS: Clasvanta v2.8.7 patch applied.")
print("Backup:", backup_dir.name)
print("DATABASE MIGRATIONS ARE REQUIRED.")
print()
print("Run next:")
print("  source .venv/bin/activate")
print("  python manage.py check")
print("  python manage.py makemigrations --check --dry-run")
print("  python manage.py migrate")
print("  python manage.py collectstatic --noinput")
print()
print("Then restart the Plesk Python application and hard-refresh the browser.")
