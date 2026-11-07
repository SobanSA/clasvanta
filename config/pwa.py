"""Minimal PWA endpoints: dynamically branded manifest and public offline fallback.

Authenticated HTML and private data are never served from a cache.
"""
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.http import require_GET

from academics.branding import get_app_branding


@require_GET
def manifest(request):
    branding = get_app_branding()
    name = str(branding.app_name or 'Clasvanta').strip() or 'Clasvanta'
    subtitle = str(branding.subtitle or 'Academic Attendance & Management').strip()
    response = JsonResponse({
        'id': '/',
        'name': name,
        'short_name': name[:20],
        'description': subtitle,
        'start_url': '/dashboard/',
        'scope': '/',
        'display': 'standalone',
        'display_override': ['standalone', 'minimal-ui'],
        'background_color': '#f6f8fc',
        'theme_color': '#0955b5',
        'icons': [
            {'src': static('pwa/icon-192.png'), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': static('pwa/icon-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': static('pwa/icon-maskable-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
    }, json_dumps_params={'ensure_ascii': False})
    response['Content-Type'] = 'application/manifest+json; charset=utf-8'
    response['Cache-Control'] = 'no-cache, max-age=0, must-revalidate'
    return response


@require_GET
def service_worker(request):
    path = Path(settings.BASE_DIR) / 'static' / 'pwa' / 'service-worker.js'
    try:
        script = path.read_text(encoding='utf-8')
    except OSError as exc:
        raise Http404('Service worker not installed') from exc
    response = HttpResponse(script, content_type='application/javascript; charset=utf-8')
    response['Cache-Control'] = 'no-cache, max-age=0, must-revalidate'
    response['Service-Worker-Allowed'] = '/'
    return response


@require_GET
def offline_page(request):
    response = render(request, 'pwa/offline.html')
    response['Cache-Control'] = 'no-cache, max-age=0, must-revalidate'
    return response
