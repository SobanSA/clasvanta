"""Isolated SQLite test settings. Never use for production or data migration."""
from .settings import *  # noqa: F403,F401

DATABASES = {
    'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'},
}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
