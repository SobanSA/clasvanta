"""Validated CSV/XLSX imports for academic setup and students.

Academic setup is designed as an idempotent source-of-truth import: re-uploading the
same rows updates the matching term/programme/class/subject/teacher assignment and
weekly schedule instead of duplicating records.
"""
import csv
import io
import re
import secrets
import string
from collections import defaultdict
from datetime import date, datetime

from django.db import transaction
from accounts.models import User
from .models import (
    AcademicTerm,
    ClassGroup,
    ClassMembership,
    ClassSubject,
    Programme,
    StudentProfile,
    Subject,
    WeeklySchedule,
)

MAX_UPLOAD_BYTES = 2_000_000
MAX_ROWS = 1500

DAY_MAP = {
    'monday': 0, 'mon': 0,
    'tuesday': 1, 'tue': 1, 'tues': 1,
    'wednesday': 2, 'wed': 2,
    'thursday': 3, 'thu': 3, 'thur': 3, 'thurs': 3,
    'friday': 4, 'fri': 4,
    'saturday': 5, 'sat': 5,
    'sunday': 6, 'sun': 6,
}
DAY_LABELS = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday', 4: 'Friday', 5: 'Saturday', 6: 'Sunday'}


def _normalize(value):
    return re.sub(r'[^a-z0-9]+', '_', str(value or '').strip().lower()).strip('_')


def parse_upload(file):
    if file.size > MAX_UPLOAD_BYTES:
        raise ValueError('File too large (maximum 2 MB).')
    filename = file.name.lower()
    if filename.endswith('.csv'):
        raw = file.read()
        # Excel/Windows commonly exports CSV files as Windows-1252 rather than UTF-8.
        # Prefer UTF-8 (including BOM), then fall back to CP1252 so punctuation such
        # as en-dashes and smart quotes does not make the whole import fail.
        content = None
        for encoding in ('utf-8-sig', 'cp1252'):
            try:
                content = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if content is None:
            raise ValueError(
                'Could not read the CSV text encoding. Save/export the file as UTF-8 CSV or Windows CSV and try again.'
            )
        rows = list(csv.reader(io.StringIO(content)))
    elif filename.endswith('.xlsx'):
        from openpyxl import load_workbook
        book = load_workbook(io.BytesIO(file.read()), read_only=True, data_only=True)
        rows = [list(r) for r in book.active.iter_rows(values_only=True)]
        book.close()
    else:
        raise ValueError('Please upload a CSV or XLSX file.')
    if not rows:
        raise ValueError('The file is empty.')
    if len(rows) - 1 > MAX_ROWS:
        raise ValueError(f'Maximum {MAX_ROWS} rows per import.')
    headers = [_normalize(v) for v in rows[0]]
    if len(headers) != len(set(headers)):
        raise ValueError('The spreadsheet contains duplicate column names.')
    data = []
    for i, values in enumerate(rows[1:], start=2):
        row = {
            head: str(values[j] if j < len(values) and values[j] is not None else '').strip()
            for j, head in enumerate(headers)
        }
        if any(row.values()):
            row['_row'] = i
            data.append(row)
    return data


def _pick(row, *keys):
    for k in keys:
        value = row.get(k)
        if value is not None and str(value).strip() != '':
            return str(value).strip()
    return ''


def _parse_iso_date(raw, label, row_no):
    raw = str(raw or '').strip()
    # Accept the ISO format used by the sample template and the DD/MM/YYYY
    # format commonly produced by Excel in Pakistan/UK-style regional settings.
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    raise ValueError(
        f'Row {row_no}: {label} must use YYYY-MM-DD or DD/MM/YYYY format.'
    )


def _parse_schedule(raw, row_no):
    """Parse `Monday:1;Wednesday:3` into a list of JSON-safe dictionaries."""
    if not raw:
        return []
    result = []
    seen = set()
    for token in re.split(r'[;|]+', raw):
        token = token.strip()
        if not token:
            continue
        if ':' in token:
            day_text, lecture_text = [v.strip() for v in token.split(':', 1)]
        else:
            day_text, lecture_text = token, '1'
        day_key = day_text.casefold()
        if day_key not in DAY_MAP:
            raise ValueError(f'Row {row_no}: unknown day "{day_text}" in schedule.')
        try:
            lecture_number = int(lecture_text)
        except ValueError:
            raise ValueError(f'Row {row_no}: lecture number in "{token}" must be a whole number.')
        if lecture_number < 1 or lecture_number > 20:
            raise ValueError(f'Row {row_no}: lecture number in "{token}" must be between 1 and 20.')
        key = (DAY_MAP[day_key], lecture_number)
        if key in seen:
            raise ValueError(f'Row {row_no}: duplicate schedule item "{token}".')
        seen.add(key)
        result.append({'weekday': key[0], 'lecture_number': key[1], 'label': f'{DAY_LABELS.get(key[0], day_text.title())}:L{lecture_number}'})
    return sorted(result, key=lambda x: (x['weekday'], x['lecture_number']))


def _password():
    alphabet = string.ascii_letters + string.digits + '!@#$%'
    return ''.join(secrets.choice(alphabet) for _ in range(16))


def validate_structure_rows(rows):
    problems = []
    normalized = []
    seen_class_subjects = set()
    term_signature = None
    programme_seen = {}
    class_seen = {}
    subject_seen = {}
    teacher_seen = {}

    for row in rows:
        no = row.get('_row', '?')
        term_name = _pick(row, 'term_name', 'academic_term', 'term')
        term_start_raw = _pick(row, 'term_start', 'start_date')
        term_end_raw = _pick(row, 'term_end', 'end_date')
        program_code = _pick(row, 'program_code', 'programme_code').upper()
        program_name = _pick(row, 'program_name', 'programme_name')
        class_code = _pick(row, 'class_code', 'class').upper()
        class_name = _pick(row, 'class_name')
        semester_raw = _pick(row, 'semester', 'semester_number')
        subject_code = _pick(row, 'subject_code', 'code').upper()
        subject_name = _pick(row, 'subject_name')
        short_name = _pick(row, 'short_name', 'subject_short_name')
        teacher_id = _pick(row, 'teacher_id', 'lecturer_id', 'teacher_username', 'lecturer_username')
        teacher_name = _pick(row, 'teacher_name', 'lecturer_name')
        schedule_raw = _pick(row, 'schedule', 'lectures', 'weekly_schedule')

        required = {
            'term_name': term_name,
            'term_start': term_start_raw,
            'term_end': term_end_raw,
            'program_code': program_code,
            'program_name': program_name,
            'class_code': class_code,
            'semester': semester_raw,
            'subject_code': subject_code,
            'subject_name': subject_name,
            'short_name': short_name,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            problems.append(f'Row {no}: missing {", ".join(missing)}.')
            continue

        try:
            term_start = _parse_iso_date(term_start_raw, 'term_start', no)
            term_end = _parse_iso_date(term_end_raw, 'term_end', no)
            semester = int(semester_raw)
            if semester < 1 or semester > 16:
                raise ValueError
            schedule = _parse_schedule(schedule_raw, no)
        except ValueError as exc:
            if str(exc).startswith('Row '):
                problems.append(str(exc))
            else:
                problems.append(f'Row {no}: semester must be a whole number from 1 to 16.')
            continue

        if term_end < term_start:
            problems.append(f'Row {no}: term_end cannot be before term_start.')
            continue
        if bool(teacher_id) != bool(teacher_name):
            problems.append(f'Row {no}: teacher_id and teacher_name must either both be filled or both be blank.')
            continue
        if len(program_code) > 24 or len(program_name) > 180 or len(class_code) > 48:
            problems.append(f'Row {no}: programme/class value exceeds maximum length.')
            continue
        if len(subject_code) > 40 or len(subject_name) > 180 or len(short_name) > 40:
            problems.append(f'Row {no}: subject value exceeds maximum length.')
            continue
        if len(teacher_id) > 150 or len(teacher_name) > 150:
            problems.append(f'Row {no}: teacher ID or name is too long.')
            continue

        if not class_name:
            class_name = f'Semester {semester}'

        sig = (term_name.casefold(), term_start.isoformat(), term_end.isoformat())
        if term_signature is None:
            term_signature = sig
        elif term_signature != sig:
            problems.append(f'Row {no}: one setup file must contain exactly one academic term with consistent dates.')
            continue

        p_key = program_code.casefold()
        if p_key in programme_seen and programme_seen[p_key] != program_name:
            problems.append(f'Row {no}: programme {program_code} has inconsistent names in this file.')
            continue
        programme_seen[p_key] = program_name

        c_key = class_code.casefold()
        c_sig = (program_code.casefold(), class_name, semester)
        if c_key in class_seen and class_seen[c_key] != c_sig:
            problems.append(f'Row {no}: class {class_code} has inconsistent programme/name/semester in this file.')
            continue
        class_seen[c_key] = c_sig

        s_key = subject_code.casefold()
        s_sig = (subject_name, short_name)
        if s_key in subject_seen and subject_seen[s_key] != s_sig:
            problems.append(f'Row {no}: subject {subject_code} has inconsistent name/short name in this file.')
            continue
        subject_seen[s_key] = s_sig

        if teacher_id:
            t_key = teacher_id.casefold()
            if t_key in teacher_seen and teacher_seen[t_key] != teacher_name:
                problems.append(f'Row {no}: teacher {teacher_id} has inconsistent names in this file.')
                continue
            teacher_seen[t_key] = teacher_name
            existing_user = User.objects.filter(username__iexact=teacher_id).first()
            if existing_user and existing_user.role != 'LECTURER':
                problems.append(f'Row {no}: username {teacher_id} already belongs to a non-lecturer account.')
                continue

        # A class may only receive a subject once. The SAME subject may appear in
        # several different classes; when the teacher_id is also the same those
        # rows are intentionally merged into one teaching section.
        class_subject_key = (class_code.casefold(), subject_code.casefold())
        if class_subject_key in seen_class_subjects:
            problems.append(
                f'Row {no}: duplicate class/subject combination {class_code} + {subject_code}. '
                'Use one row per class and subject.'
            )
            continue
        seen_class_subjects.add(class_subject_key)

        # Unassigned subjects are kept class-specific. Once a teacher is known,
        # subject + teacher becomes the merged section identity for this term.
        if teacher_id:
            merge_key = f'{subject_code.casefold()}::{teacher_id.casefold()}'
            section_code = f'{short_name}-{teacher_id}'[:60]
        else:
            merge_key = f'{subject_code.casefold()}::__class__::{class_code.casefold()}'
            section_code = short_name[:60]

        existing_term = AcademicTerm.objects.filter(name__iexact=term_name).first()
        existing_program = Programme.objects.filter(code__iexact=program_code).first()
        existing_class = None
        if existing_term:
            existing_class = ClassGroup.objects.filter(term=existing_term, code__iexact=class_code).first()
        existing_subject = Subject.objects.filter(code__iexact=subject_code).first()
        existing_teacher = User.objects.filter(username__iexact=teacher_id).first() if teacher_id else None
        existing_offering = None
        if existing_term and existing_subject:
            qs = ClassSubject.objects.filter(subject=existing_subject, class_groups__term=existing_term).distinct()
            if teacher_id and existing_teacher:
                existing_offering = qs.filter(lecturer=existing_teacher).first()
            elif existing_class:
                existing_offering = qs.filter(lecturer__isnull=True, class_groups=existing_class).first()

        changes = []
        changes.append('Update term' if existing_term else 'Create term')
        changes.append('Update programme' if existing_program else 'Create programme')
        changes.append('Update class' if existing_class else 'Create class')
        changes.append('Update subject' if existing_subject else 'Create subject')
        if teacher_id:
            changes.append('Update teacher' if existing_teacher else 'Create teacher')
        changes.append('Merge/update teaching section' if existing_offering else 'Create teaching section')
        if schedule:
            changes.append('Merge weekly schedule')

        normalized.append({
            'term_name': term_name,
            'term_start': term_start.isoformat(),
            'term_end': term_end.isoformat(),
            'program_code': program_code,
            'program_name': program_name,
            'class_code': class_code,
            'class_name': class_name,
            'semester': semester,
            'subject_code': subject_code,
            'subject_name': subject_name,
            'short_name': short_name,
            'section_code': section_code,
            'teacher_id': teacher_id,
            'teacher_name': teacher_name,
            'schedule': schedule,
            'schedule_text': '; '.join(x['label'] for x in schedule) if schedule else 'No weekly lecture set',
            'changes': changes,
            'merge_key': merge_key,
            '_row': no,
        })

    # Add a human-readable merged-class preview to every source row. This keeps
    # validation transparent: the admin can see exactly which class rows will be
    # combined into one subject section before confirming the import.
    merged = defaultdict(list)
    for item in normalized:
        if item['class_code'] not in merged[item['merge_key']]:
            merged[item['merge_key']].append(item['class_code'])
    for item in normalized:
        classes = merged[item['merge_key']]
        item['merged_classes'] = ', '.join(classes)
        item['merge_count'] = len(classes)

    return normalized, problems

def validate_student_rows(rows):
    problems = []
    normalized = []
    terms = list(AcademicTerm.objects.filter(is_active=True))
    if len(terms) != 1:
        return [], ['Exactly one active academic term is required before importing students.']
    term = terms[0]
    class_map = {c.code.casefold(): c for c in ClassGroup.objects.filter(term=term)}
    seen = set()

    for row in rows:
        no = row.get('_row', '?')
        registration = _pick(row, 'registration_number', 'student_registration_number', 'registration_no', 'student_id')
        name = _pick(row, 'student_name', 'name')
        class_code = _pick(row, 'class', 'class_code', 'his_class').upper()
        missing = [k for k, v in [('registration_number', registration), ('student_name', name), ('class_code', class_code)] if not v]
        if missing:
            problems.append(f'Row {no}: missing {", ".join(missing)}.')
            continue
        if len(registration) > 150 or len(name) > 150:
            problems.append(f'Row {no}: registration number or name too long.')
            continue
        if registration.casefold() in seen:
            problems.append(f'Row {no}: duplicate registration number in file: {registration}.')
            continue
        seen.add(registration.casefold())
        if class_code.casefold() not in class_map:
            problems.append(f'Row {no}: unknown class {class_code} for active term {term.name}.')
            continue
        existing = User.objects.filter(username__iexact=registration).first()
        if existing and existing.role != 'STUDENT':
            problems.append(f'Row {no}: registration number {registration} belongs to a non-student account.')
            continue
        normalized.append({
            'registration_number': registration,
            'student_name': name,
            'class': class_map[class_code.casefold()].code,
            'action': 'Update' if existing else 'Create',
            '_row': no,
        })
    return normalized, problems


def validate_rows(kind, rows):
    if kind == 'structure':
        return validate_structure_rows(rows)
    if kind == 'students':
        return validate_student_rows(rows)
    return [], ['Unsupported import type.']


@transaction.atomic
def import_structure(rows):
    if not rows:
        raise ValueError('No rows to import.')

    first = rows[0]
    term, _ = AcademicTerm.objects.get_or_create(
        name=first['term_name'],
        defaults={
            'start_date': date.fromisoformat(first['term_start']),
            'end_date': date.fromisoformat(first['term_end']),
            'is_active': True,
        },
    )
    term.start_date = date.fromisoformat(first['term_start'])
    term.end_date = date.fromisoformat(first['term_end'])
    term.is_active = True
    term.full_clean()
    AcademicTerm.objects.exclude(pk=term.pk).filter(is_active=True).update(is_active=False)
    term.save()

    credentials = []
    stats = {
        'programmes': set(), 'classes': set(), 'subjects': set(), 'teachers': set(),
        'offerings': 0, 'schedules': 0,
    }
    prepared = []

    # First build/update the catalogue objects from each CSV row.
    for row in rows:
        programme, _ = Programme.objects.get_or_create(
            code=row['program_code'], defaults={'name': row['program_name']},
        )
        if programme.name != row['program_name']:
            programme.name = row['program_name']
            programme.full_clean(); programme.save(update_fields=['name'])
        stats['programmes'].add(programme.pk)

        group, _ = ClassGroup.objects.get_or_create(
            term=term,
            code=row['class_code'],
            defaults={
                'name': row['class_name'],
                'programme': programme,
                'semester_number': row['semester'],
            },
        )
        changed = False
        if group.name != row['class_name']:
            group.name = row['class_name']; changed = True
        if group.programme_id != programme.pk:
            group.programme = programme; changed = True
        if group.semester_number != row['semester']:
            group.semester_number = row['semester']; changed = True
        if changed:
            group.full_clean(); group.save()
        stats['classes'].add(group.pk)

        subject, _ = Subject.objects.get_or_create(
            code=row['subject_code'],
            defaults={'name': row['subject_name'], 'short_name': row['short_name']},
        )
        s_changed = False
        if subject.name != row['subject_name']:
            subject.name = row['subject_name']; s_changed = True
        if subject.short_name != row['short_name']:
            subject.short_name = row['short_name']; s_changed = True
        if s_changed:
            subject.full_clean(); subject.save()
        stats['subjects'].add(subject.pk)

        lecturer = None
        if row['teacher_id']:
            lecturer = User.objects.filter(username__iexact=row['teacher_id']).first()
            if lecturer is None:
                password = _password()
                lecturer = User(
                    username=row['teacher_id'],
                    first_name=row['teacher_name'],
                    role='LECTURER',
                    must_change_password=True,
                )
                lecturer.set_password(password)
                lecturer.full_clean(); lecturer.save()
                credentials.append([row['teacher_id'], row['teacher_name'], password])
            else:
                if lecturer.role != 'LECTURER':
                    raise ValueError(f'Username {row["teacher_id"]} is not a lecturer account.')
                if lecturer.first_name != row['teacher_name']:
                    lecturer.first_name = row['teacher_name']
                    lecturer.save(update_fields=['first_name'])
            stats['teachers'].add(lecturer.pk)

        prepared.append({
            'row': row,
            'group': group,
            'subject': subject,
            'lecturer': lecturer,
        })

    # Merge rows into subject-based teaching sections. Same term + subject +
    # teacher = one section, even when the rows belong to different programmes or
    # classes. If there is no teacher yet, keep the row class-specific.
    buckets = {}
    for item in prepared:
        row = item['row']
        lecturer = item['lecturer']
        if lecturer:
            key = (item['subject'].pk, lecturer.pk)
        else:
            key = (item['subject'].pk, None, item['group'].pk)
        bucket = buckets.setdefault(key, {
            'subject': item['subject'], 'lecturer': lecturer, 'classes': {}, 'schedules': {},
            'section_code': row['section_code'],
        })
        bucket['classes'][item['group'].pk] = item['group']
        for sch in row['schedule']:
            bucket['schedules'][(sch['weekday'], sch['lecture_number'])] = sch

    for bucket in buckets.values():
        classes = sorted(bucket['classes'].values(), key=lambda c: (c.programme.code, c.semester_number, c.code))
        primary = classes[0]
        subject = bucket['subject']
        lecturer = bucket['lecturer']
        class_ids = [c.pk for c in classes]

        # Prefer an existing section with exactly the same subject+teacher in this
        # term. This makes re-uploads idempotent. If none exists, create one.
        qs = ClassSubject.objects.filter(subject=subject, class_groups__term=term).distinct()
        if lecturer:
            offering = qs.filter(lecturer=lecturer).first()
        else:
            offering = qs.filter(lecturer__isnull=True, class_groups=primary).first()

        # If the teacher changed since the previous CSV, reuse an existing section
        # only when all of its currently linked classes are part of this new bucket.
        # That updates the teacher without disturbing another class that still uses
        # the old teacher.
        if offering is None:
            current_ids = set(class_ids)
            candidates = ClassSubject.objects.filter(
                subject=subject, class_groups__in=classes, class_groups__term=term
            ).distinct()
            for candidate in candidates:
                linked_ids = set(candidate.class_groups.values_list('pk', flat=True))
                if linked_ids and linked_ids.issubset(current_ids):
                    offering = candidate
                    break

        if offering is None:
            offering = ClassSubject(
                class_group=primary,
                subject=subject,
                lecturer=lecturer,
                section_code=bucket['section_code'],
            )
            offering.full_clean(); offering.save()
        else:
            changed = False
            if offering.class_group_id not in class_ids:
                offering.class_group = primary; changed = True
            if offering.lecturer_id != (lecturer.pk if lecturer else None):
                offering.lecturer = lecturer; changed = True
            if offering.section_code != bucket['section_code']:
                offering.section_code = bucket['section_code']; changed = True
            if changed:
                offering.full_clean(); offering.save()

        # This CSV is the source of truth for the classes in the merged section.
        # Add current classes, and detach these class+subject pairs from any other
        # active section to prevent duplicate assignments after a teacher change.
        offering.class_groups.add(*class_ids)
        for group in classes:
            others = ClassSubject.objects.filter(
                subject=subject,
                class_groups=group,
                class_groups__term=term,
            ).exclude(pk=offering.pk).distinct()
            for old in others:
                old.class_groups.remove(group)
                # Remove empty unused shells safely. Historical sections with
                # attendance/fines are retained so audit/history is never lost.
                if not old.class_groups.exists() and not old.lecture_sessions.exists() and not old.fine_entries.exists():
                    old.weekly_schedules.all().delete()
                    old.delete()

        # Rebuild the section schedule from the UNION of schedule entries across
        # every row that merged into this section.
        offering.weekly_schedules.all().delete()
        for sch in sorted(bucket['schedules'].values(), key=lambda x: (x['weekday'], x['lecture_number'])):
            entry = WeeklySchedule(
                class_subject=offering,
                weekday=sch['weekday'],
                lecture_number=sch['lecture_number'],
            )
            entry.full_clean(); entry.save()
            stats['schedules'] += 1

        stats['offerings'] += 1

    return credentials, {
        'programmes': len(stats['programmes']),
        'classes': len(stats['classes']),
        'subjects': len(stats['subjects']),
        'teachers': len(stats['teachers']),
        'offerings': stats['offerings'],
        'schedules': stats['schedules'],
        'term': term.name,
    }


@transaction.atomic
def import_students(rows):
    term = AcademicTerm.objects.get(is_active=True)
    credentials = []
    created = 0
    updated = 0
    for row in rows:
        user = User.objects.filter(username__iexact=row['registration_number']).first()
        if user is None:
            password = _password()
            user = User(
                username=row['registration_number'],
                first_name=row['student_name'],
                role='STUDENT',
                must_change_password=True,
            )
            user.set_password(password)
            user.full_clean(); user.save()
            credentials.append([row['registration_number'], row['student_name'], row['class'], password])
            created += 1
        else:
            if user.role != 'STUDENT':
                raise ValueError(f'{row["registration_number"]} belongs to a non-student account.')
            if user.first_name != row['student_name']:
                user.first_name = row['student_name']
                user.save(update_fields=['first_name'])
            updated += 1

        profile, _ = StudentProfile.objects.get_or_create(user=user)
        group = ClassGroup.objects.get(term=term, code=row['class'])
        membership, was_created = ClassMembership.objects.update_or_create(
            student=profile,
            term=term,
            defaults={'class_group': group},
        )
        membership.full_clean()
    return credentials, {'created': created, 'updated': updated, 'term': term.name}
