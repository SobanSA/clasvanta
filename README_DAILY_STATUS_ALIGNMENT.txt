Clasvanta — Daily Class Status alignment hotfix

1. Upload install_daily_status_alignment.py into attendance_app/ beside manage.py.
2. Activate venv:
   source .venv/bin/activate
3. Run:
   python install_daily_status_alignment.py
4. Then:
   python manage.py check
   python manage.py collectstatic --noinput
5. Restart the Python application in Plesk.

No database migration is required.
The installer creates a timestamped backup of both changed files.
