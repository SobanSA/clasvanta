#!/usr/bin/env python3
"""Clasvanta hotfix: align Daily Class Status date selector/actions.

Run from the project root (directory containing manage.py):
    source .venv/bin/activate
    python install_daily_status_alignment.py

No database migration is required.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import sys

ROOT = Path.cwd().resolve()
TEMPLATE = ROOT / 'templates' / 'attendance' / 'admin_sessions.html'
CSS = ROOT / 'static' / 'css' / 'admin_usability.css'

for path in (ROOT / 'manage.py', TEMPLATE, CSS):
    if not path.exists():
        print(f'ERROR: required file not found: {path}')
        print('Run this installer from the attendance_app directory containing manage.py.')
        sys.exit(1)

old_block = '''<section class="panel attendance-date-panel daily-status-date-panel">
  <form method="get" class="attendance-date-form">
    <div>
      <label for="attendanceDate">Select date</label>
      <input id="attendanceDate" type="date" name="date"
             value="{{ selected_date|date:'Y-m-d' }}"
             min="{{ active_term.start_date|date:'Y-m-d' }}"
             max="{{ active_term.end_date|date:'Y-m-d' }}">
      <small>{{ active_term.name }} · {{ active_term.start_date|date:"j M Y" }} – {{ active_term.end_date|date:"j M Y" }}</small>
    </div>
    <button class="btn btn-primary" type="submit">Show classes</button>
    {% if today_in_term and not is_today %}<a class="btn btn-secondary" href="{% url 'admin_sessions' %}">Today</a>{% endif %}
  </form>
</section>'''

new_block = '''<section class="panel attendance-date-panel daily-status-date-panel">
  <form method="get" class="attendance-date-form daily-status-date-form">
    <div class="daily-status-date-field">
      <label for="attendanceDate">Select date</label>
      <input id="attendanceDate" type="date" name="date"
             value="{{ selected_date|date:'Y-m-d' }}"
             min="{{ active_term.start_date|date:'Y-m-d' }}"
             max="{{ active_term.end_date|date:'Y-m-d' }}">
      <small>{{ active_term.name }} · {{ active_term.start_date|date:"j M Y" }} – {{ active_term.end_date|date:"j M Y" }}</small>
    </div>
    <div class="daily-status-date-actions">
      <button class="btn btn-primary" type="submit">Show classes</button>
      {% if today_in_term and not is_today %}<a class="btn btn-secondary" href="{% url 'admin_sessions' %}">Today</a>{% endif %}
    </div>
  </form>
</section>'''

css_marker = '/* Daily class status date-filter alignment hotfix */'
css_rules = r'''

/* Daily class status date-filter alignment hotfix */
.daily-status-date-panel .daily-status-date-form{
  display:grid;
  grid-template-columns:minmax(250px,320px) auto;
  align-items:start;
  gap:14px;
}
.daily-status-date-panel .daily-status-date-field{
  display:grid;
  gap:6px;
  min-width:0;
}
.daily-status-date-panel .daily-status-date-field input[type=date]{
  width:100%;
  min-width:0;
}
.daily-status-date-panel .daily-status-date-field small{
  min-height:16px;
  font-size:10px;
  line-height:1.4;
  color:var(--muted);
}
.daily-status-date-panel .daily-status-date-actions{
  display:flex;
  align-items:center;
  gap:10px;
  padding-top:26px;
  flex-wrap:wrap;
}
.daily-status-date-panel .daily-status-date-actions .btn{
  min-width:145px;
}
@media(max-width:760px){
  .daily-status-date-panel .daily-status-date-form{
    grid-template-columns:1fr;
    gap:12px;
  }
  .daily-status-date-panel .daily-status-date-actions{
    padding-top:0;
    width:100%;
  }
  .daily-status-date-panel .daily-status-date-actions .btn{
    flex:1 1 160px;
  }
}
@media(max-width:480px){
  .daily-status-date-panel .daily-status-date-actions{
    display:grid;
    grid-template-columns:1fr;
  }
  .daily-status-date-panel .daily-status-date-actions .btn{
    width:100%;
  }
}
'''

template_text = TEMPLATE.read_text(encoding='utf-8')
css_text = CSS.read_text(encoding='utf-8')

already = 'class="attendance-date-form daily-status-date-form"' in template_text and css_marker in css_text
if already:
    print('Already installed: Daily Class Status date filter is aligned.')
    sys.exit(0)

if old_block not in template_text:
    print('ERROR: The expected Daily Class Status date panel was not found.')
    print('This installer is designed for the daily-class-status patch currently installed.')
    print('No files were changed.')
    sys.exit(1)

new_template = template_text.replace(old_block, new_block, 1)
new_css = css_text if css_marker in css_text else css_text.rstrip() + css_rules + '\n'

stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
backup = ROOT / f'backup_daily_status_alignment_{stamp}'
(backup / 'templates' / 'attendance').mkdir(parents=True, exist_ok=True)
(backup / 'static' / 'css').mkdir(parents=True, exist_ok=True)
shutil.copy2(TEMPLATE, backup / 'templates' / 'attendance' / 'admin_sessions.html')
shutil.copy2(CSS, backup / 'static' / 'css' / 'admin_usability.css')

# Write only after all validation and backups succeed.
TEMPLATE.write_text(new_template, encoding='utf-8')
CSS.write_text(new_css, encoding='utf-8')

print('SUCCESS: Daily Class Status date filter alignment installed.')
print(f'Backup created: {backup.name}')
print('Next commands:')
print('  python manage.py check')
print('  python manage.py collectstatic --noinput')
print('Then restart the Python application in Plesk.')
