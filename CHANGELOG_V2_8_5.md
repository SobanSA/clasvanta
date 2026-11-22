# Clasvanta v2.8.5 — Fine Challans & Timetable Compliance

## Fine payment challan
- Adds an **A5 portrait** attendance-fine payment challan.
- Designed for economical **black-and-white printing**.
- Adds **Print challan** beside outstanding student fine entries.
- Challan consolidates the student's current positive subject balances from the existing append-only fine ledger.
- Shows student identity, programme/class/term, total absences, fineable absences, course-wise outstanding balances, issue date, due date and cashier receipt area.
- Current ledger payments/adjustments remain authoritative; no second fine engine is introduced.

## Configurable institute name
- Adds a separate **Institute name** field to Super Admin → Settings → Application branding.
- Default institute name is **Clasvanta**.
- Institute name is independent from the application/PWA name.
- No real institution name is embedded in the public source.

## Reports
- Rewrites the Monthly missing & make-up lectures note as end-user guidance.
- Adds **Lec in timetable compliance** report.
- Report is grouped by lecturer, class and subject and shows weekly timetable slots, expected regular lectures, Held, Missing, Held make-up, delivered total and compliance percentage.
- Cancelled lectures remain in the separate Schedule compliance report.
- Only Held make-up lectures compensate for missing delivery, and compliance is capped at 100%.
- Excel export and print/Save-as-PDF are supported through the existing report framework.

## Database
- Additive migration `academics/migrations/0006_appbranding_institute_name.py`.
- Existing academic, attendance, fine and audit data are not altered or deleted.
