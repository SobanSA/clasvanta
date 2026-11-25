"""Canonical WhatsApp-number formatting (syntax only, no account verification)."""
import re


def normalize_whatsapp_number(value):
    """Return an E.164-style string, or '' for optional blank input.

    Accept Pakistani mobile numbers in local 03XXXXXXXXX format, or an
    international number beginning with + (or 00). Formatting separators are
    removed. International format is checked syntactically, not against a carrier.
    """
    value = (value or '').strip()
    if not value:
        return ''
    if len(value) > 64 or not re.fullmatch(r'[+0-9 ()\-]+', value):
        raise ValueError('Enter a valid WhatsApp number, e.g. 03001234567 or +923001234567.')
    number = re.sub(r'[ ()\-]', '', value)
    if number.startswith('00'):
        number = '+' + number[2:]
    if re.fullmatch(r'03[0-9]{9}', number):
        number = '+92' + number[1:]
    if not re.fullmatch(r'\+[1-9][0-9]{7,14}', number):
        raise ValueError('Use a Pakistani mobile number (03XXXXXXXXX) or an international number with country code (+...).')
    if number.startswith('+92') and not re.fullmatch(r'\+923[0-9]{9}', number):
        raise ValueError('Enter a Pakistani mobile number with 10 digits after +92, beginning with 3.')
    return number
