"""PWA regression tests. Run with --settings=config.test_settings."""
from django.test import TestCase


class PWATests(TestCase):
    def test_manifest(self):
        response = self.client.get('/manifest.webmanifest')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('application/manifest+json'))
        data = response.json()
        self.assertEqual(data['name'], 'Clasvanta')
        self.assertEqual(data['display'], 'standalone')
        self.assertEqual(data['scope'], '/')
        self.assertEqual(data['start_url'], '/dashboard/')
        self.assertTrue(any('maskable' in item['purpose'] for item in data['icons']))

    def test_worker(self):
        response = self.client.get('/service-worker.js')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Service-Worker-Allowed'], '/')
        self.assertIn(b'const CACHE_NAME', response.content)
        self.assertIn(b"req.mode === 'navigate'", response.content)

    def test_offline_page(self):
        response = self.client.get('/offline/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You're offline")

    def test_login_includes_manifest(self):
        response = self.client.get('/login/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'rel="manifest"')
        self.assertContains(response, 'pwa/install.js')
