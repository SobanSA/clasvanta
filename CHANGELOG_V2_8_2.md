# Clasvanta v2.8.2 — Lecturer Name Consistency Hotfix

## Fixed

- Dashboard **Recent attendance** now displays the lecturer assigned to the subject section (`ClassSubject.lecturer`) instead of the account that submitted the attendance (`LectureSession.submitted_by`).
- This makes Dashboard lecturer names consistent with Reports, Attendance management, Academic Structure, Teaching Assignments, Make-up Classes, and student subject summaries.
- `submitted_by` remains unchanged and is still used where the UI explicitly means **Recorded by**, **Submitted by**, or audit actor.
- Added a regression test covering the exact case where an administrator submits attendance on behalf of a lecturer.

## Database

No migration is required. No attendance, fine, audit, academic, student, or lecturer data is changed.
