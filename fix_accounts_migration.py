#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path.cwd()
mig_dir = ROOT / "accounts" / "migrations"
old = mig_dir / "0002_accounts_role.py"
new = mig_dir / "0003_accounts_role.py"
existing = mig_dir / "0002_user_must_change_password.py"

if not (ROOT / "manage.py").exists():
    sys.exit("ERROR: Run this from the attendance_app directory containing manage.py.")
if not existing.exists():
    sys.exit("ERROR: accounts/migrations/0002_user_must_change_password.py was not found.")
if not old.exists() and not new.exists():
    sys.exit("ERROR: Neither 0002_accounts_role.py nor 0003_accounts_role.py was found.")

source = old if old.exists() else new
text = source.read_text(encoding="utf-8")
text = text.replace(
    "('accounts', '0001_initial'),",
    "('accounts', '0002_user_must_change_password'),",
    1,
)

new.write_text(text, encoding="utf-8")

if old.exists() and old != new:
    old.unlink()

print("SUCCESS: Accounts migration corrected.")
print("Current file: accounts/migrations/0003_accounts_role.py")
print("Dependency: accounts/0002_user_must_change_password")
print()
print("Run next:")
print("  python manage.py makemigrations --check --dry-run")
print("  python manage.py migrate")
print("  python manage.py collectstatic --noinput")
