# Clasvanta v2.8.4 — Monthly Missing & Make-up Report

## Added / refined

- Added the spreadsheet-style monthly lecturer exception register under Reports.
- Columns: #, Teacher Name, Class, Lec in timetable, Date, Day, Status, Remarks.
- The duration / “No. of Lec / 1.5 Hour” column is intentionally omitted.
- The report contains:
  - **Held Lecture** — a regular timetable lecture with submitted attendance.
  - **Missing Lecture** — a past recurring timetable occurrence that remains unmarked.
  - **Make-up Lecture** — an approved make-up occurrence that has not been cancelled.
- **Cancelled** and future **Scheduled** lectures are excluded from this report and remain available through the existing compliance/daily reports.
- Existing month, programme, class, subject, and lecturer filters apply.
- Excel export uses the same columns and filtered rows.
- Merged sections are expanded per linked class so the report remains class-specific.
- “Lec in timetable” counts recurring timetable slots for that lecturer/class in the filtered scope; make-up lectures do not inflate this number.

## Database

No migration required.
