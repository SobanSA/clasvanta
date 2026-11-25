# Clasvanta

**Academic Attendance & Management**

Clasvanta is a Django-based academic attendance management system for administrators, lecturers, accounts staff, and students. This repository contains the **consolidated v2.8.10 source**: the historical patch releases and the live maintenance patches have been folded into the application files, so a fresh download does **not** require running any `apply_patch.py` or `install_*.py` scripts.

## Current capabilities

- Programme → academic term → class → subject structure
- Merged teaching sections across multiple classes
- Lecturer assignment and recurring weekday/lecture-number scheduling
- Inline lecture assignment from subject-section cards, including multi-day weekday selection
- Attendance states: **Pending / Not Marked**, **Held**, and **Cancelled**
- Lecturer same-day attendance workflow and submission history
- Controlled attendance corrections with audit history
- Super Admin-only Held-session deletion with permanent deletion audit
- Approved one-off make-up classes
- Daily Class Status view with date selection, Held/Pending/Cancelled state, and dashboard counters
- Student portal: dashboard, attendance, schedule, fines, profile, and weekly timetable
- Lecturer profile with regular weekly teaching workload
- Student management: add, edit, activate/deactivate, safe delete, and explicitly confirmed force delete
- Staff-facing Student Profiles directory, academic overview and enrolment history; Admin-only temporary student password reset
- Compulsory student contact completion: father name and active WhatsApp number, plus staff search/filter support
- Accounts role with restricted student/fine access and read-only fine access
- Fine reconciliation based on absences from Held classes
- Super Admin fine concession and current-balance waiver with append-only ledger history
- A5 black-and-white fine payment challans
- Monthly missing/make-up lecturer register
- Timetable compliance, schedule compliance, daily/class/student/defaulter/fine reports
- Excel export and print/Save-as-PDF reporting
- Configurable application branding and separate institute name
- Installable Progressive Web App (PWA) with refreshed v2.8.8 icons
- Mobile-first responsive interface

## Roles and permissions

### Super Admin

A Django superuser has full application access, Advanced Administration, application branding, student management, reports, and fine concession/waiver controls.

### Admin

Application administrators can manage academics, lecturers, students, attendance, make-up classes, reports, and normal fine workflows. Destructive or sensitive actions remain restricted where explicitly stated in the UI/code.

### Accounts

The `Accounts` application role is synchronized from the Django Group named **Accounts**. Accounts users can use the main application for:

- Enrolled students
- Student attendance lookup
- Student Profiles: search and view academic/contact information, attendance, and fines
- Add/edit student details
- Fines and student fine ledger/history
- Fine challan printing

Accounts users do not receive Advanced Administration, academic setup, lecturer management, attendance-management, reporting, bulk-import, settings, or student-deletion permissions. Fine access is read-only. Student password resets and account activation/deactivation are restricted to Admin and Super Admin.

### Lecturer

Lecturers can see today's lectures, mark attendance within the configured rules, view their submissions, request make-up classes, and view their recurring weekly workload.

### Student

Students have read-only academic views for their dashboard, attendance, schedule, weekly timetable and fines. After any required password change, they must complete their missing contact details. They can update their WhatsApp number and password, but identity and academic details are administrator-controlled.

## Attendance semantics

A timetable occurrence is not automatically a conducted class.

- **Pending / Not Marked:** scheduled but attendance has not been submitted.
- **Held:** attendance was submitted. Only Held classes count in attendance denominators and absence/fine logic.
- **Cancelled:** retained in schedule history but does not count as Held and creates no absence/fine.

Approved make-up classes are one-off dated classes and remain separate from the recurring timetable. Only Held make-up classes contribute to delivered/compliance calculations where applicable.

## Student deletion behaviour

Student deletion is intentionally controlled:

- A student with no protected attendance/audit/fine history can be safely deleted after explicit confirmation.
- A student account can be activated or deactivated without deleting history.
- Force Delete is an explicit administrative action that removes the target student's student-specific attendance, audit, fine-ledger, membership, profile, and login records and scrubs that student from saved deleted-session snapshots.
- Force Delete is irreversible; take a database backup before using it when the records may be needed later.

## Fine relief behaviour

Fine charges remain append-only ledger history. Super Admin concession/waiver actions add auditable relief entries with an actor, timestamp, and required reason; they do not delete the original charges. Relief normalization prevents a later attendance correction from turning prior relief into unintended credit against future fines.

## Branding and PWA

Default identity:

- **Application name:** Clasvanta
- **Subtitle:** Academic Attendance & Management
- **Institute name:** Clasvanta

A Django superuser can change these values from **Settings → Application branding**. The application name drives the UI/PWA identity; institute name is used for official printouts such as fine challans.

The PWA provides a dynamic manifest, root-scoped service worker, offline guidance, install prompts, and phone/desktop icons. The service worker intentionally caches only public static assets and the generic offline page; authenticated student, attendance, fine, report, and dashboard pages are not cached for offline viewing.

Production PWA installation normally requires HTTPS.

## Technology

- Python 3
- Django 5.2
- MariaDB/MySQL in production
- SQLite for isolated tests
- openpyxl for Excel exports

## Environment variables and secrets

Production secrets must be supplied through the host environment. Do **not** commit a production `.env` file.

Required:

```text
DJANGO_SECRET_KEY=<strong-random-secret>
ATTENDANCE_DB_PASSWORD=<database-password>
```

Recommended:

```text
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=attendance.example.edu
DJANGO_CSRF_TRUSTED_ORIGINS=https://attendance.example.edu
ATTENDANCE_DB_NAME=clasvanta
ATTENDANCE_DB_USER=clasvanta
ATTENDANCE_DB_HOST=localhost
ATTENDANCE_DB_PORT=3306
```

Copy `.env.example` only as a reference for variable names. The committed application settings read the Django secret and database password from environment variables and contain no production password or production Django secret.

## Clean installation / deployment

This repository is now a complete application source tree. **Do not run historical patch installers.** They are already consolidated into the current files.

Create/activate a virtual environment, install dependencies, configure the environment variables, and run:

```bash
pip install -r requirements.txt
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py collectstatic --noinput
```

For a new installation, also create a superuser:

```bash
python manage.py createsuperuser
```

Then configure the WSGI/ASGI host and restart the application. `public/static/`, local backups, private uploads, `.env`, and virtual environments are intentionally not version-controlled.

## Tests

Use the isolated SQLite settings:

```bash
DJANGO_SECRET_KEY=test-only-secret python manage.py test --settings=config.test_settings
```

For a deployment sanity check, at minimum run:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
```

## Student contact details (v2.8.9)

All students must provide a father's name and an active WhatsApp number before accessing their student portal. Forced password change always takes priority. Existing details are preserved; only missing fields are requested. The student may supply a missing father's name once, but cannot edit the saved name, registration ID or academic details. The WhatsApp number can be changed at any time from My Profile; it cannot be cleared by the student. Admin and Accounts users can add or correct these fields and filter/search the enrolled roster. The database migration adds an optional `whatsapp_number` field without altering historical records. Phone numbers are normalized and syntax-checked; no OTP or WhatsApp API is used. Keep contact details private and restrict access to authorized staff.

## Student profiles and password resets (v2.8.10)

Open Students → Student profiles from the main application as Admin, Super Admin or Accounts. Search by registration number, name, father name or WhatsApp number. Search includes inactive accounts and historical enrolments; results are not displayed until a search is submitted, and selecting a student opens a dedicated profile. Attendance uses current-term Held records; weekly lectures use the recurring timetable; outstanding fines sum positive subject-section ledger balances across all terms. Accounts can view the profile and use existing student-edit, attendance and fine permissions, but cannot reset passwords or manage activation status.

Admin and Super Admin can reset a student password from Enrolled students or Student profiles. Confirm the target student to generate a secure temporary password, shown only on the successful non-cacheable response. Copy it immediately; it is not saved in a session or included in a URL or message. Refreshing/replaying the confirmation cannot reset the password again. Old passwords and existing authenticated sessions become invalid. The student must change the temporary password before completing any missing contact information or accessing academic pages. Resetting does not reactivate an inactive account or alter any academic/contact records.

## Release history

### v2.8.10 — Staff student profiles and password reset

- Added a searchable staff-facing Student Profiles screen and profile links in Enrolled students for Admin, Super Admin and Accounts.
- Added profile completeness/account status, contact details, current-term metrics, assigned subjects/lecturers, weekly timetable, all-term fine balance and enrolment history.
- Added Admin/Super Admin-only student password reset with explicit confirmation, one-time password display, replay protection and compulsory password change.
- Preserved v2.8.9 student contact completion and existing permissions. No database migration or new dependency.

### v2.8.9 — Compulsory student contact completion

- Added a server-side completion gate for existing and new students, after the forced-password-change step.
- Collect only missing father's name and WhatsApp number; no skip option. Previously saved father's names remain locked to students.
- Student self-service WhatsApp updates, normalized Pakistani/international formats, and backend validation.
- Admin/Accounts optional contact entry/correction and roster display, search and completion filtering.
- New migration `academics/migrations/0008_studentprofile_whatsapp_number.py`. No manual SQL or data reset.
- Added regression tests for onboarding, direct URL protection, permissions, validation and contact management.

### v2.8.8 — App icon refresh

- Replaced favicon/PWA/Apple/maskable icon assets with the current Clasvanta icon set.
- Added cache-busting icon URLs and refreshed the service-worker cache version so old icon assets are discarded.
- No database migration.

### v2.8.7 — Accounts permissions, student editing, and fine relief

- Added the **Accounts** application role synchronized from the Django `Accounts` group.
- Restricted Accounts users to student/fine workflows and kept them out of Advanced Administration.
- Added Super Admin-only partial fine concession and full current-outstanding waiver with auditable ledger entries.
- Added optional student father name, father-name searches, and student edit support for registration/login ID, student name, and father name.
- Added migrations:
  - `accounts/migrations/0003_accounts_role.py`
  - `academics/migrations/0007_studentprofile_father_name.py`
  - `fines/migrations/0002_fineledgerentry_relief_kinds.py`

### Consolidated maintenance after v2.8.6

These changes were originally shipped as local installer patches and are now part of the normal source tree:

- Lecturer and student **weekly profile/workload** views derived from the recurring timetable.
- Controlled student deletion.
- Student activation/deactivation, safe deletion, and explicit Force Delete with snapshot scrubbing.
- **Daily Class Status** page and corrected make-up dashboard counters.
- Daily Class Status date-selector/action alignment hotfix.
- No additional database migration for these maintenance changes.

### v2.8.6 — Lecture assignments workflow

- Moved lecture day/number editing into each subject-section card.
- Removed the duplicated lower weekly-slot edit list.
- Replaced the single weekday dropdown with weekday checkboxes.
- Allowed one submission to assign the same lecture number to multiple selected days.
- Expanded assignment verification search to weekday names and lecture numbers.
- Preserved existing clash/duplicate validation and historical attendance behaviour.
- No database migration.

### v2.8.5 — Fine challans and timetable compliance

- Added A5 black-and-white attendance-fine challans.
- Added separate configurable **Institute name** branding.
- Added **Lec in timetable compliance** reporting with Held/Missing/Make-up delivery calculations and capped compliance percentage.
- Refined the monthly missing/make-up report guidance.
- Added `academics/migrations/0006_appbranding_institute_name.py`.

### v2.8.4 — Monthly missing & make-up lecturer register

- Added the spreadsheet-style monthly lecturer exception register.
- Included Held Lecture, Missing Lecture, and Make-up Lecture rows.
- Excluded Cancelled and future Scheduled rows from that report.
- Added matching Excel export and class-specific expansion for merged sections.
- No database migration.

### v2.8.3 — Installable PWA

- Added dynamic `/manifest.webmanifest`, root `/service-worker.js`, and `/offline/` endpoints.
- Added install guidance for Android/desktop and iOS home-screen installation.
- Kept authenticated/private records out of Cache Storage.
- Added PWA icon assets and PWA tests.
- No database migration.

### v2.8.2 — Lecturer name consistency hotfix

- Dashboard Recent Attendance now displays the lecturer assigned to the subject section rather than the account that submitted the attendance.
- `submitted_by` remains available for audit/Recorded by/Submitted by semantics.
- Added regression coverage.
- No database migration.

### v2.8.1 — Configurable application branding

- Introduced the Clasvanta default application name and subtitle.
- Added Super Admin-only application branding settings and propagation through UI, reports, Excel headings, and Django administration.
- Added environment-based allowed-host and CSRF-origin configuration.
- Added `academics/migrations/0005_appbranding.py`.

## Repository hygiene

The repository should contain deployable source, migrations, tests, templates, static source assets, and examples only. Historical patch installers, patch payloads, local backup directories, generated `public/static/`, database files, imported private spreadsheets, and production secrets are deliberately excluded.

## License

**Free to Use — Attribution Required**

This project is free to use, modify, and distribute, including for personal, educational, and commercial purposes. The attribution requirement is described in [`LICENSE`](LICENSE).

This software is provided **"as is"**, without warranty.
