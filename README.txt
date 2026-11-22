Clasvanta v2.8.7 Accounts migration hotfix

Use this ONLY if you already ran the v2.8.7 apply_patch.py and then received:

Conflicting migrations detected:
(0002_accounts_role, 0002_user_must_change_password in accounts)

Fix:
1. Upload fix_accounts_migration.py to attendance_app/ beside manage.py.
2. Run:

   cd /path/to/attendance_app
   source .venv/bin/activate
   python fix_accounts_migration.py
   python manage.py check
   python manage.py makemigrations --check --dry-run
   python manage.py migrate
   python manage.py collectstatic --noinput

3. Restart the Plesk Python application.

Do NOT run makemigrations --merge for this conflict.
