"""Forms shared by student self-service and the Django administration."""
from django import forms
from django.core.exceptions import ValidationError

from .contact_details import normalize_whatsapp_number


class WhatsAppNumberField(forms.CharField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('label', 'Active WhatsApp number')
        kwargs.setdefault('max_length', 64)
        kwargs.setdefault('help_text', 'Enter 03001234567 or an international number such as +923001234567. Use a number you can currently receive WhatsApp messages on.')
        kwargs.setdefault('widget', forms.TextInput(attrs={
            'type': 'tel', 'inputmode': 'tel', 'autocomplete': 'tel',
            'placeholder': '03001234567',
        }))
        super().__init__(*args, **kwargs)

    def clean(self, value):
        value = super().clean(value)
        try:
            value = normalize_whatsapp_number(value)
        except ValueError as exc:
            raise ValidationError(str(exc), code='invalid') from exc
        if self.required and not value:
            raise ValidationError(self.error_messages['required'], code='required')
        return value


class ContactCompletionForm(forms.Form):
    father_name = forms.CharField(
        label="Father's full name", max_length=160, strip=True,
        help_text='Check the spelling before saving. Only the administration can correct it afterwards.',
        widget=forms.TextInput(attrs={'autocomplete': 'off', 'placeholder': "Enter father's full name"}),
    )
    whatsapp_number = WhatsAppNumberField()

    def __init__(self, profile, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Derive allowed fields exclusively from the current server-side record.
        if not profile.missing_father_name:
            self.fields.pop('father_name')
        if not profile.missing_whatsapp_number:
            self.fields.pop('whatsapp_number')


class WhatsAppUpdateForm(forms.Form):
    whatsapp_number = WhatsAppNumberField()
