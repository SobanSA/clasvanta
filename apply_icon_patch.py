#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
import shutil
import sys

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PAYLOAD = HERE / "payload"

required = [
    ROOT / "manage.py",
    ROOT / "templates" / "base.html",
    ROOT / "config" / "pwa.py",
    ROOT / "static" / "pwa" / "service-worker.js",
]
for path in required:
    if not path.exists():
        sys.exit(f"ERROR: required file not found: {path.relative_to(ROOT)}")
if not PAYLOAD.exists():
    sys.exit("ERROR: payload folder is missing. Upload the whole extracted patch folder.")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = ROOT / f".app_icon_v288_backup_{stamp}"
backup_dir.mkdir()

def backup(path):
    if path.exists():
        dest = backup_dir / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one matching block, found {count}.")
    return text.replace(old, new, 1)

try:
    # Back up files that will be modified/replaced.
    for path in required:
        backup(path)
    for name in [
        "icon-192.png", "icon-512.png", "icon-maskable-512.png",
        "apple-touch-icon.png", "favicon-64.png",
    ]:
        backup(ROOT / "static" / "pwa" / name)

    # Copy generated icon assets.
    icon_src = PAYLOAD / "static" / "pwa"
    icon_dst = ROOT / "static" / "pwa"
    icon_dst.mkdir(parents=True, exist_ok=True)
    for name in [
        "icon-192.png", "icon-512.png", "icon-maskable-512.png",
        "apple-touch-icon.png", "favicon-64.png",
    ]:
        shutil.copy2(icon_src / name, icon_dst / name)

    # Browser/PWA HTML icon references with a new cache-busting version.
    base_path = ROOT / "templates" / "base.html"
    text = base_path.read_text(encoding="utf-8")
    old_favicon = """<meta name="theme-color" content="#f6f8fc"><link rel="icon" type="image/svg+xml" href="{% static 'img/favicon.svg' %}?v=281"><title>"""
    new_favicon = """<meta name="theme-color" content="#f6f8fc"><link rel="icon" type="image/png" sizes="64x64" href="{% static 'pwa/favicon-64.png' %}?v=288"><title>"""
    if old_favicon in text:
        text = text.replace(old_favicon, new_favicon, 1)
    elif "pwa/favicon-64.png" not in text:
        raise RuntimeError("templates/base.html: original favicon reference was not found.")

    text = text.replace(
        """href="{% static 'pwa/apple-touch-icon.png' %}">""",
        """href="{% static 'pwa/apple-touch-icon.png' %}?v=288">""",
        1,
    )
    text = text.replace(
        """href="{% static 'pwa/icon-192.png' %}">""",
        """href="{% static 'pwa/icon-192.png' %}?v=288">""",
        1,
    )
    base_path.write_text(text, encoding="utf-8")

    # Cache-bust manifest icon URLs.
    pwa_path = ROOT / "config" / "pwa.py"
    text = pwa_path.read_text(encoding="utf-8")
    replacements = {
        """{'src': static('pwa/icon-192.png'), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'}""":
        """{'src': f"{static('pwa/icon-192.png')}?v=288", 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'}""",
        """{'src': static('pwa/icon-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'}""":
        """{'src': f"{static('pwa/icon-512.png')}?v=288", 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'}""",
        """{'src': static('pwa/icon-maskable-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'}""":
        """{'src': f"{static('pwa/icon-maskable-512.png')}?v=288", 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'}""",
    }
    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new, 1)
        elif "?v=288" not in text:
            raise RuntimeError("config/pwa.py: expected manifest icon line was not found.")
    pwa_path.write_text(text, encoding="utf-8")

    # Force a new service-worker cache so old icon bytes are discarded.
    sw_path = ROOT / "static" / "pwa" / "service-worker.js"
    text = sw_path.read_text(encoding="utf-8")
    text = text.replace(
        "/* Clasvanta 2.8.3 — public assets only. NEVER cache attendance or private pages. */",
        "/* Clasvanta 2.8.8 — refreshed app icons; public assets only. NEVER cache attendance or private pages. */",
        1,
    )
    if "const CACHE_NAME = 'clasvanta-static-v2.8.3';" in text:
        text = text.replace(
            "const CACHE_NAME = 'clasvanta-static-v2.8.3';",
            "const CACHE_NAME = 'clasvanta-static-v2.8.8-icon';",
            1,
        )
    elif "clasvanta-static-v2.8.8-icon" not in text:
        raise RuntimeError("service-worker.js: CACHE_NAME line was not found.")

    text = text.replace(
        "OFFLINE, '/static/pwa/icon-192.png', '/static/pwa/icon-512.png',",
        "OFFLINE, '/static/pwa/icon-192.png?v=288', '/static/pwa/icon-512.png?v=288',",
        1,
    )
    text = text.replace(
        "'/static/pwa/icon-maskable-512.png', '/static/pwa/apple-touch-icon.png',",
        "'/static/pwa/icon-maskable-512.png?v=288', '/static/pwa/apple-touch-icon.png?v=288',",
        1,
    )
    sw_path.write_text(text, encoding="utf-8")

except Exception as exc:
    print(f"ERROR: {exc}")
    print(f"Backup created at: {backup_dir.name}")
    sys.exit(1)

print("SUCCESS: Clasvanta app icon patch v2.8.8 applied.")
print(f"Backup: {backup_dir.name}")
print("No database migration is required.")
print()
print("Run next:")
print("  python manage.py check")
print("  python manage.py collectstatic --noinput")
print()
print("Then restart the Plesk Python application and hard-refresh the browser.")
print("If an already-installed PWA still shows the old launcher icon, uninstall that")
print("installed app once and reinstall it so the operating system refreshes its icon.")
