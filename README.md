# Clasvanta

**Academic Attendance & Management**

Clasvanta is a Django-based academic attendance system for administrators, lecturers and students. It supports recurring lecture schedules, merged teaching sections, attendance marking and correction, make-up classes, fines, student self-service, audit history, and schedule/attendance reporting.

## Highlights

- Programme → term → class → subject academic structure
- Merged subject sections across multiple classes
- Lecturer assignments and day + lecture-number scheduling
- Attendance states: **Pending**, **Held**, **Cancelled**
- Controlled attendance correction with audit history
- Super Admin-only Held-session deletion with permanent deletion audit
- Approved one-off make-up classes
- Student portal: dashboard, attendance, schedule, fines and profile
- Fine reconciliation based only on absences from Held classes
- Schedule compliance, daily/class/student/defaulter/fine reports
- Excel export and print/Save-as-PDF reports
- Mobile-first responsive UI
- Configurable institution/application branding

## Branding

The default identity is:

- **Name:** Clasvanta
- **Subtitle:** Academic Attendance & Management

A Django superuser can change both from **Settings → Application branding**. The configured identity is used throughout the main interface and report headings.

## Technology

- Python 3
- Django 5.2
- MariaDB/MySQL in production
- SQLite in the isolated test configuration
- openpyxl for Excel exports

## Environment variables

Required for production:

```text
DJANGO_SECRET_KEY=<strong-random-secret>
ATTENDANCE_DB_PASSWORD=<database-password>
```

Recommended for public/self-hosted deployments:

```text
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=attendance.example.edu
DJANGO_CSRF_TRUSTED_ORIGINS=https://attendance.example.edu
ATTENDANCE_DB_NAME=<database-name>
ATTENDANCE_DB_USER=<database-user>
ATTENDANCE_DB_HOST=localhost
ATTENDANCE_DB_PORT=3306
```

The repository contains no production secret key or database password.

## Installation

Create a virtual environment, install dependencies, configure the environment variables above, then run:

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --noinput
```

Configure your WSGI/ASGI host to serve the Django application and `/static/` from the collected static directory.

## Tests

Use the isolated SQLite test settings:

```bash
DJANGO_SECRET_KEY=test-only-secret python manage.py test --settings=config.test_settings
```

## Attendance semantics

A timetable occurrence is not automatically a conducted class.

- **Pending / Not Marked:** scheduled, but attendance has not been submitted.
- **Held:** attendance was submitted. Only Held classes count in attendance denominators and absence/fine logic.
- **Cancelled:** retained in history but does not count as Held and creates no absence/fine.

Approved make-up classes are one-off dated classes and remain separate from the recurring timetable.

## Public repository hygiene

Do not commit production secrets, database dumps, imported student spreadsheets, or collected static output. The supplied `.gitignore` excludes common local/private artifacts.

## Installable Progressive Web App (v2.8.3)

Clasvanta is installable as a standalone PWA on compatible Android, iPhone/iPad, Windows, and macOS devices over HTTPS. Chromium browsers can expose **Install app**; on iPhone/iPad Safari use **Share → Add to Home Screen**.

The dynamic `/manifest.webmanifest` reflects the Super Admin's application name and subtitle. A root-scoped service worker caches only public static assets and a generic offline guidance page. Private pages, attendance, reports, student records, and fines stay **online-only**.

PWA setup on a Plesk-hosted Django installation: update the files, run `python manage.py check`, run `python manage.py collectstatic --noinput`, restart the application, and confirm that the manifest and service-worker URLs load successfully. No database migration is needed. See `INSTALL_V2_8_3.txt`.

## License

**Free to Use — Attribution Required**
This project is free and open for everyone to use, modify, and distribute, including for personal, educational, and commercial purposes.
No payment, subscription, or prior permission is required.
The only requirement is to give proper credit to the original developer and include a link to this GitHub repository: https://github.com/SobanSA/clasvanta
This software is provided "as is", without any warranty.
