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
- A5 black-and-white fine payment challans with per-student print action
- Schedule compliance, daily/class/student/defaulter/fine reports
- Monthly lecturer register and Lec in timetable compliance reporting
- Excel export and print/Save-as-PDF reports
- Mobile-first responsive UI
- Configurable application branding and separate institute name for official printouts
- Installable Progressive Web App (PWA) for phones, tablets and desktop computers

## Branding

The default identity is:

- **Name:** Clasvanta
- **Subtitle:** Academic Attendance & Management

A Django superuser can change the product name/subtitle and a separate **Institute name** from **Settings → Application branding**. The institute name defaults to **Clasvanta** and is used on official printouts such as fine payment challans, while the application name continues to control the product UI and PWA identity.

## Progressive Web App (PWA)

Clasvanta can be installed as a standalone app while still using the same Django server and database. The PWA uses the current Super Admin-configured application name in its web app manifest.

Installation options:

- **Android (Chrome/Edge):** use the in-app **Install app** button when offered, or the browser menu → **Install app / Add to Home screen**.
- **iPhone/iPad (Safari):** Share → **Add to Home Screen**.
- **Windows/macOS/Linux (Chrome/Edge and other supporting browsers):** use the browser's install-app control or the in-app **Install app** button when offered.

Production PWA installation requires HTTPS (localhost is the usual development exception). Run `collectstatic` after deployment so the PWA icons and JavaScript are available.

### Offline/privacy behaviour

The service worker intentionally caches only static assets and a generic offline page. Authenticated pages and records — including attendance, student data, fines, reports and dashboards — are **not** stored in Cache Storage. When the server/network is unavailable, the app shows the offline fallback rather than serving stale private records.

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

## License

**Free to Use — Attribution Required**

This project is free for everyone to use, modify and distribute, including for personal, educational and commercial purposes. No payment, subscription or prior permission is required.

The only requirement is to give proper credit to the original developer and include a link to [this GitHub repository](./). This software is provided **"as is"**, without any warranty.

See the full terms in [`LICENSE`](LICENSE).
