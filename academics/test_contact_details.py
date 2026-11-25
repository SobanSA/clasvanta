"""Dependency-free tests for WhatsApp syntax and normalization."""
import unittest

from .contact_details import normalize_whatsapp_number


class WhatsAppNormalizationTests(unittest.TestCase):
    def test_pakistani_formats_are_canonical(self):
        for value in ('03001234567', '0300-1234567', '0300 1234567', '+923001234567', '+92 (300) 1234567', '00923001234567'):
            with self.subTest(value=value):
                self.assertEqual(normalize_whatsapp_number(value), '+923001234567')

    def test_international_formats(self):
        self.assertEqual(normalize_whatsapp_number('+44 7700 900123'), '+447700900123')
        self.assertEqual(normalize_whatsapp_number('0044 7700 900123'), '+447700900123')
        self.assertEqual(normalize_whatsapp_number('+1 (202) 555-0123'), '+12025550123')
        self.assertEqual(normalize_whatsapp_number('+123456789012345'), '+123456789012345')

    def test_blank_is_supported_for_staff(self):
        for value in ('', '   ', None):
            self.assertEqual(normalize_whatsapp_number(value), '')

    def test_invalid_numbers(self):
        for value in ('0300123456', '030012345678', '+9203001234567', '+92511234567',
                      '3001234567', '12345', '+1234567', '+0123456789', '+1234567890123456',
                      '+92 3001234567 ext 1', '+92abc1234567', '++923001234567',
                      '۰۳۰۰۱۲۳۴۵۶۷', '---', '0'*65):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_whatsapp_number(value)
