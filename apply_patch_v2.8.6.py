#!/usr/bin/env python3
from pathlib import Path
import shutil
import sys

ROOT = Path.cwd()

FILES = {
    "academics/views.py": ROOT / "academics/views.py",
    "templates/academics/lecture_schedule.html": ROOT / "templates/academics/lecture_schedule.html",
    "static/css/lecture_picker.css": ROOT / "static/css/lecture_picker.css",
}

for label, path in FILES.items():
    if not path.exists():
        sys.exit(f"ERROR: {label} not found. Run this script from the Clasvanta project root.")

def backup(path: Path):
    backup_path = path.with_suffix(path.suffix + ".bak_lecture_inline_v286")
    if not backup_path.exists():
        shutil.copy2(path, backup_path)
    return backup_path

def replace_once(text, old, new, label):
    if old not in text:
        sys.exit(f"ERROR: Expected block not found in {label}. No changes saved to that file.")
    return text.replace(old, new, 1)

# 1) Backend: allow one subject section + one lecture number on many days.
views = FILES["academics/views.py"]
backup(views)
v = views.read_text(encoding="utf-8")

old = """            if action == 'add':
                offering=ClassSubject.objects.filter(pk=int(request.POST['offering']), class_groups__term=active).distinct().get()
                obj=WeeklySchedule(class_subject=offering, weekday=int(request.POST['weekday']), lecture_number=int(request.POST['lecture_number']))
                obj.full_clean(); obj.save(); messages.success(request,'Lecture assignment added.')
            elif action == 'edit':"""

new = """            if action == 'add':
                offering=ClassSubject.objects.filter(pk=int(request.POST['offering']), class_groups__term=active).distinct().get()
                raw_weekdays=request.POST.getlist('weekdays')
                if not raw_weekdays and request.POST.get('weekday'):
                    # Backward compatibility for an older cached single-day form.
                    raw_weekdays=[request.POST['weekday']]
                if not raw_weekdays:
                    raise ValueError('Select at least one lecture day.')

                valid_days={value for value, _label in WeeklySchedule.DAYS}
                weekdays=[]
                for raw_day in raw_weekdays:
                    day=int(raw_day)
                    if day not in valid_days:
                        raise ValueError('Invalid lecture day.')
                    if day not in weekdays:
                        weekdays.append(day)

                lecture_number=int(request.POST['lecture_number'])
                with transaction.atomic():
                    for weekday in weekdays:
                        obj=WeeklySchedule(
                            class_subject=offering,
                            weekday=weekday,
                            lecture_number=lecture_number,
                        )
                        obj.full_clean()
                        obj.save()

                count=len(weekdays)
                messages.success(
                    request,
                    f'{count} lecture assignment{"s" if count != 1 else ""} added.'
                )
            elif action == 'edit':"""

v = replace_once(v, old, new, "academics/views.py")
views.write_text(v, encoding="utf-8")

# 2) Template changes.
tpl = FILES["templates/academics/lecture_schedule.html"]
backup(tpl)
t = tpl.read_text(encoding="utf-8")

t = t.replace(
    """<link rel="stylesheet" href="{% static 'css/lecture_picker.css' %}?v=254">""",
    """<link rel="stylesheet" href="{% static 'css/lecture_picker.css' %}?v=286">""",
    1,
)

old = """ <div class="lecture-slot-field"><label for="lecture-slot-weekday">Day</label><select id="lecture-slot-weekday" name="weekday" required>{% for value,label in days %}<option value="{{ value }}">{{ label }}</option>{% endfor %}</select></div>
 <div class="lecture-slot-field"><label for="lecture-slot-number">Lecture number</label><input id="lecture-slot-number" type="number" min="1" max="20" name="lecture_number" value="1" required></div>"""

new = """ <div class="lecture-slot-field lecture-day-field">
   <span class="lecture-slot-label">Days</span>
   <div class="lecture-day-options" role="group" aria-label="Lecture days">
     {% for value,label in days %}
     <label class="lecture-day-check"><input type="checkbox" name="weekdays" value="{{ value }}" {% if forloop.first %}checked{% endif %}><span>{{ label }}</span></label>
     {% endfor %}
   </div>
   <small class="course-picker-help">Select one or more days for the same lecture number.</small>
 </div>
 <div class="lecture-slot-field"><label for="lecture-slot-number">Lecture number</label><input id="lecture-slot-number" type="number" min="1" max="20" name="lecture_number" value="1" required></div>"""

t = replace_once(t, old, new, "lecture_schedule.html day selector")

old = """<input id="verification-course-search" type="search" data-course-list-search placeholder="Search course name, code, class, teacher name or ID…" autocomplete="off">"""
new = """<input id="verification-course-search" type="search" data-course-list-search placeholder="Search course, class, teacher, ID, day or lecture…" autocomplete="off">"""
t = replace_once(t, old, new, "lecture_schedule.html search placeholder")

old = """data-search="{{ o.subject.name }} {{ o.subject.code }} {{ o.section_code }} {{ o.class_codes_display }} {% if o.lecturer %}{{ o.lecturer.get_full_name }} {{ o.lecturer.username }}{% endif %} {% if o.is_ready %}ready{% else %}needs setup{% endif %}">"""
new = """data-search="{{ o.subject.name }} {{ o.subject.code }} {{ o.section_code }} {{ o.class_codes_display }} {% if o.lecturer %}{{ o.lecturer.get_full_name }} {{ o.lecturer.username }}{% endif %} {% for slot in o.display_schedules %}{{ slot.get_weekday_display }} Lecture {{ slot.lecture_number }} L{{ slot.lecture_number }} {% endfor %}{% if o.is_ready %}ready{% else %}needs setup{% endif %}">"""
t = replace_once(t, old, new, "lecture_schedule.html card search index")

old = """      <div class="course-list-card-aside">
        <span class="course-list-card-label">Assigned lectures</span>
        <div class="lecture-pill-group">{% for slot in o.display_schedules %}<span class="schedule-pill">{{ slot.get_weekday_display }} · Lecture {{ slot.lecture_number }}</span>{% empty %}<span class="warning-text">No lectures</span>{% endfor %}</div>
        {% if not o.is_ready %}<p class="course-list-card-warning">{% if o.missing_teacher %}Assign a teacher. {% endif %}{% if o.inactive_teacher %}Teacher inactive. {% endif %}{% if o.missing_schedule %}Assign a lecture number. {% endif %}{% if o.has_conflict %}Resolve timetable clash.{% endif %}</p>{% endif %}
      </div>"""

new = """      <div class="course-list-card-aside">
        <div class="course-list-card-label-row">
          <span class="course-list-card-label">Assigned lectures</span>
          {% if o.display_schedules %}
          <details class="lecture-inline-editor">
            <summary>Edit</summary>
            <div class="lecture-inline-editor-body">
              {% for slot in o.display_schedules %}
              <div class="lecture-inline-row">
                <form method="post" class="lecture-inline-form">
                  {% csrf_token %}
                  <input type="hidden" name="action" value="edit">
                  <input type="hidden" name="id" value="{{ slot.pk }}">
                  <div class="lecture-edit-field">
                    <label for="inline-weekday-{{ slot.pk }}">Day</label>
                    <select id="inline-weekday-{{ slot.pk }}" name="weekday">
                      {% for value,label in days %}
                      <option value="{{ value }}" {% if slot.weekday == value %}selected{% endif %}>{{ label }}</option>
                      {% endfor %}
                    </select>
                  </div>
                  <div class="lecture-edit-field lecture-inline-number">
                    <label for="inline-number-{{ slot.pk }}">Lecture</label>
                    <input id="inline-number-{{ slot.pk }}" type="number" min="1" max="20" name="lecture_number" value="{{ slot.lecture_number }}" required>
                  </div>
                  <button type="submit" class="btn btn-small">Save</button>
                </form>
                <form method="post" class="lecture-inline-remove">
                  {% csrf_token %}
                  <input type="hidden" name="action" value="delete">
                  <input type="hidden" name="id" value="{{ slot.pk }}">
                  <button class="btn btn-small btn-danger" type="submit" data-confirm="Remove this lecture assignment? Past attendance records will be preserved.">Remove</button>
                </form>
              </div>
              {% endfor %}
            </div>
          </details>
          {% endif %}
        </div>
        <div class="lecture-pill-group">{% for slot in o.display_schedules %}<span class="schedule-pill">{{ slot.get_weekday_display }} · Lecture {{ slot.lecture_number }}</span>{% empty %}<span class="warning-text">No lectures</span>{% endfor %}</div>
        {% if not o.is_ready %}<p class="course-list-card-warning">{% if o.missing_teacher %}Assign a teacher. {% endif %}{% if o.inactive_teacher %}Teacher inactive. {% endif %}{% if o.missing_schedule %}Assign a lecture number. {% endif %}{% if o.has_conflict %}Resolve timetable clash.{% endif %}</p>{% endif %}
      </div>"""

t = replace_once(t, old, new, "lecture_schedule.html inline editor")

weekly_marker = """<section class="panel lecture-results-panel" data-course-list>
  <div class="panel-head lecture-list-head">
    <div><h2>Weekly lecture slots</h2>"""
pos = t.find(weekly_marker)
if pos == -1:
    sys.exit("ERROR: Weekly lecture slots section not found in lecture_schedule.html.")
endblock = t.find("{% endblock %}", pos)
if endblock == -1:
    sys.exit("ERROR: Template endblock not found after Weekly lecture slots.")
t = t[:pos] + t[endblock:]

tpl.write_text(t, encoding="utf-8")

# 3) CSS for checkbox day picker + card-local editor.
css = FILES["static/css/lecture_picker.css"]
backup(css)
c = css.read_text(encoding="utf-8")

marker = "/* v2.8.6 — Multi-day assignment and card-local lecture editing. */"
if marker not in c:
    c += r"""

/* v2.8.6 — Multi-day assignment and card-local lecture editing. */
.lecture-slot-label {
  margin:0; line-height:16px; min-height:16px;
  color:#60728a; font-size:11px; font-weight:800; text-transform:uppercase;
}
.stack-form .lecture-slot-grid {
  grid-template-columns:minmax(300px,1.1fr) minmax(380px,1.35fr) minmax(150px,.55fr);
}
.lecture-day-field { min-width:0; }
.lecture-day-options {
  display:flex; flex-wrap:wrap; gap:7px;
  min-height:62px; align-content:center;
  padding:8px 10px; border:1px solid #dce4ed; border-radius:10px; background:#fff;
}
.lecture-day-check {
  display:inline-flex; align-items:center; gap:6px;
  margin:0; padding:7px 10px;
  border:1px solid #dce5ef; border-radius:999px;
  background:#f8fafc; color:#42566f;
  font-size:11px; font-weight:700; cursor:pointer;
  user-select:none;
}
.lecture-day-check input {
  width:15px!important; height:15px!important; min-height:0!important;
  margin:0!important; padding:0!important;
}
.lecture-day-check:has(input:checked) {
  border-color:#9ebce8; background:#edf4fe; color:#1757a7;
}
.course-list-card-label-row {
  display:flex; align-items:center; justify-content:space-between; gap:10px;
  margin-bottom:8px;
}
.course-list-card-label-row .course-list-card-label { margin:0; }
.lecture-inline-editor { position:relative; }
.lecture-inline-editor > summary {
  list-style:none; cursor:pointer; user-select:none;
  color:#1757a7; font-size:11px; font-weight:800;
  padding:6px 10px; border:1px solid #cfdcf0; border-radius:8px;
  background:#f3f7fd;
}
.lecture-inline-editor > summary::-webkit-details-marker { display:none; }
.lecture-inline-editor[open] > summary { background:#eaf2fd; }
.lecture-inline-editor-body {
  margin-top:10px; display:flex; flex-direction:column; gap:8px;
}
.lecture-inline-row {
  display:flex; align-items:flex-end; gap:8px; flex-wrap:wrap;
  padding:10px; border:1px solid #e1e8f2; border-radius:10px; background:#fbfcfe;
}
.lecture-inline-form {
  display:grid; grid-template-columns:minmax(130px,1fr) minmax(90px,.55fr) auto;
  gap:8px; align-items:end; flex:1 1 330px; margin:0;
}
.lecture-inline-form .lecture-edit-field { gap:4px; }
.lecture-inline-form select,
.lecture-inline-form input {
  width:100%; height:38px; min-height:38px; margin:0;
  padding:7px 9px; border:1px solid #dce5f0; border-radius:8px;
  background:#fff; color:#17283f;
}
.lecture-inline-form .btn,
.lecture-inline-remove .btn {
  min-height:38px; margin:0; padding:7px 12px;
}
.lecture-inline-remove { margin:0; }

@media(max-width:1000px) {
  .stack-form .lecture-slot-grid { grid-template-columns:1fr; }
}
@media(max-width:620px) {
  .lecture-day-options { min-height:0; }
  .lecture-day-check { flex:1 1 calc(50% - 7px); justify-content:flex-start; }
  .lecture-inline-form { grid-template-columns:minmax(0,1fr) 95px; }
  .lecture-inline-form .btn { grid-column:1 / -1; width:100%; }
  .lecture-inline-remove { width:100%; }
  .lecture-inline-remove .btn { width:100%; }
}
"""
css.write_text(c, encoding="utf-8")

print("Clasvanta Lecture Assignments local patch applied successfully.")
print("Changed:")
for p in FILES.values():
    print(" -", p.relative_to(ROOT))
print("\nBackups end with: .bak_lecture_inline_v286")
print("No database migration is required.")
