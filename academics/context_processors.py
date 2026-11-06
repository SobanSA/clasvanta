from .branding import get_app_branding


def app_branding(request):
    """Expose current application branding to every rendered template."""
    return {'app_branding': get_app_branding()}
