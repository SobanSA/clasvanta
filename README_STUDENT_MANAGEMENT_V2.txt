Clasvanta — Student Management v2
=================================

Adds:
- Activate / deactivate student account from Enrolled Students and Manage Student.
- Safe delete when no historical records exist.
- Explicit Force Delete for a student with history.
- Force Delete removes student-specific attendance records, attendance audit rows,
  fine ledger entries, all memberships, student profile/login, and scrubs the student
  from saved deleted-session audit snapshots. Other students' records remain intact.
- Improved padding/layout for the Manage Student page.

Install
-------
1. Upload install_student_management_v2.py to attendance_app/ beside manage.py.
2. cd ~/attendance_app
3. source .venv/bin/activate
4. python install_student_management_v2.py
5. python manage.py check
6. python manage.py test academics.test_student_deletion
7. python manage.py collectstatic --noinput
8. Restart the Plesk Python application.

No database migration is required.
The installer creates a timestamped backup of files it modifies.

IMPORTANT
---------
Force Delete is irreversible database deletion. Take a database backup before using
it if the student data could ever be needed again.
