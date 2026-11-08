"""Centralized application branding for Clasvanta.

Runtime branding is stored in :class:`academics.models.AppBranding`.  The
fallback values keep templates and exports usable during first deploys and
while migrations are being applied.
"""
from types import SimpleNamespace

from django.db import OperationalError, ProgrammingError

DEFAULT_APP_NAME = 'Clasvanta'
DEFAULT_SUBTITLE = 'Academic Attendance & Management'
DEFAULT_INSTITUTE_NAME = 'Clasvanta'


def default_branding():
    return SimpleNamespace(
        app_name=DEFAULT_APP_NAME,
        subtitle=DEFAULT_SUBTITLE,
        institute_name=DEFAULT_INSTITUTE_NAME,
        updated_at=None,
        updated_by=None,
    )


def get_app_branding():
    """Return the singleton branding row, or safe defaults if unavailable."""
    from .models import AppBranding

    try:
        branding = AppBranding.objects.filter(pk=1).first()
    except (OperationalError, ProgrammingError):
        branding = None
    return branding or default_branding()
