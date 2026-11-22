Clasvanta controlled student deletion installer

Purpose:
- Adds a Delete action to Enrolled students.
- ADMIN users can permanently delete a student only when there is NO attendance, audit, or fine history.
- Students with protected historical records are not deleted.
- Requires typing the registration number before deletion.
- Creates a timestamped backup.
- No database migration required.

Install:
1. Upload install_student_delete.py beside manage.py.
2. Activate venv.
3. python install_student_delete.py
4. python manage.py check
5. python manage.py test academics.test_student_deletion
6. Restart the Plesk Python app.
