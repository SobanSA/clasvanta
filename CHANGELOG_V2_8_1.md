# Clasvanta v2.8.1 — Configurable Application Branding

v2.8.1 is a backward-compatible branding release on top of v2.8.0 Schedules & Reports.

## Added

- New default public product name: **Clasvanta**.
- New default subtitle: **Academic Attendance & Management**.
- Super Admin-only **Settings → Application branding** screen.
- Application name and subtitle are stored in a singleton database record.
- Branding now propagates to:
  - sign-in screen;
  - sidebar identity;
  - top breadcrumb;
  - browser/page titles;
  - footer;
  - report print/PDF headers;
  - Excel report headings;
  - Django advanced administration header.
- Neutral attendance/check favicon so later renames do not leave a fixed product initial behind.
- Environment overrides for `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` for public/self-hosted deployments.
- Branding authorization regression tests.

## Security / permissions

Only `is_superuser=True` accounts can open or submit the branding settings page. Ordinary application ADMIN accounts receive HTTP 403 even if the URL is entered manually.

## Database

Adds one table through:

`academics/migrations/0005_appbranding.py`

The migration creates and seeds the singleton row with the Clasvanta defaults. It does not alter or delete any existing academic, student, attendance, fine, report or audit data.

## Compatibility

All v2.8.0 reporting, Held-session deletion, student portal, merged sections, fine reconciliation and attendance-state rules remain unchanged.
