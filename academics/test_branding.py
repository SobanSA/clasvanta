from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from .models import AppBranding


class BrandingV281Tests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='brandadmin',
            password='Example123!',
        )
        self.admin = User.objects.create_user(
            username='ordinaryadmin',
            password='Example123!',
            role=User.Role.ADMIN,
            is_staff=True,
        )

    def test_default_branding_is_seeded(self):
        branding = AppBranding.objects.get(pk=1)
        self.assertEqual(branding.app_name, 'Clasvanta')
        self.assertEqual(branding.subtitle, 'Academic Attendance & Management')

    def test_superuser_can_change_branding(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse('branding_settings_manage'),
            {
                'app_name': 'Northbridge Campus',
                'subtitle': 'Attendance & Academic Operations',
            },
        )
        self.assertRedirects(response, reverse('branding_settings_manage'))
        branding = AppBranding.objects.get(pk=1)
        self.assertEqual(branding.app_name, 'Northbridge Campus')
        self.assertEqual(branding.subtitle, 'Attendance & Academic Operations')
        self.assertEqual(branding.updated_by, self.superuser)

        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'Northbridge Campus')
        self.assertContains(response, 'Attendance &amp; Academic Operations')

    def test_ordinary_admin_cannot_open_branding_settings(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('branding_settings_manage'))
        self.assertEqual(response.status_code, 403)

    def test_branding_requires_nonempty_values(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse('branding_settings_manage'),
            {'app_name': '   ', 'subtitle': '   '},
        )
        self.assertEqual(response.status_code, 200)
        branding = AppBranding.objects.get(pk=1)
        self.assertEqual(branding.app_name, 'Clasvanta')
        self.assertEqual(branding.subtitle, 'Academic Attendance & Management')

    def test_login_page_uses_current_branding(self):
        branding = AppBranding.objects.get(pk=1)
        branding.app_name = 'Campus One'
        branding.subtitle = 'Academic Services'
        branding.updated_by = self.superuser
        branding.save()

        response = self.client.get(reverse('login'))
        self.assertContains(response, 'Campus One')
        self.assertContains(response, 'Academic Services')
