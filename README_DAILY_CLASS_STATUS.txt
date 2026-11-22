Clasvanta — Daily Class Status + Make-up Dashboard Counter Fix
==============================================================

Upload install_daily_class_status.py beside manage.py, activate the existing venv, then run:

python install_daily_class_status.py
python manage.py check
DJANGO_SETTINGS_MODULE=config.test_settings python manage.py test attendance.test_daily_class_status
python manage.py collectstatic --noinput

Restart the Python application in Plesk.
No migration is required.
