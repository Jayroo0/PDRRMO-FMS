from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.models import User
from django.utils import timezone

from .models import Driver, VehicleRequest


class DriverAccountForm(forms.Form):
    driver_id = forms.ChoiceField(required=False)
    name = forms.CharField(max_length=100, required=False)
    username = forms.CharField(max_length=150)
    password = forms.CharField(
        widget=forms.PasswordInput,
        strip=False,
    )
    license_number = forms.CharField(max_length=50, required=False)
    phone_number = forms.CharField(max_length=20, required=False)

    def __init__(self, *args, available_drivers=None, **kwargs):
        super().__init__(*args, **kwargs)
        available_drivers = available_drivers or Driver.objects.filter(user__isnull=True, is_active=True)
        self.fields['driver_id'].choices = [
            ('', 'Create a new driver record'),
            *[(str(driver.id), driver.name) for driver in available_drivers],
        ]
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'

    def clean_driver_id(self):
        driver_id = self.cleaned_data['driver_id']
        if driver_id and not Driver.objects.filter(
            id=driver_id,
            user__isnull=True,
            is_active=True,
        ).exists():
            raise forms.ValidationError('Select an active driver without a login account.')
        return driver_id

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('A user with this username already exists.')
        return username

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if not self.cleaned_data.get('driver_id') and not name:
            raise forms.ValidationError('Enter a driver name or select an existing driver.')
        if name and not self.cleaned_data.get('driver_id') and Driver.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError('A driver with this name is already registered.')
        return name

    def clean_password(self):
        password = self.cleaned_data['password']
        password_validation.validate_password(password)
        return password


class VehicleRequestForm(forms.ModelForm):
    requested_for = forms.DateTimeField(
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(
            attrs={'type': 'datetime-local'},
            format='%Y-%m-%dT%H:%M',
        ),
    )

    class Meta:
        model = VehicleRequest
        fields = [
            'requester_name',
            'organization',
            'contact_number',
            'purpose',
            'vehicle_category',
            'requested_for',
            'pickup_location',
            'destination',
            'details',
        ]
        widgets = {
            'details': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css_class = 'form-select' if isinstance(field.widget, forms.Select) else 'form-control'
            field.widget.attrs['class'] = css_class

    def clean_requested_for(self):
        requested_for = self.cleaned_data['requested_for']
        if timezone.is_naive(requested_for):
            requested_for = timezone.make_aware(requested_for)
        if requested_for <= timezone.now():
            raise forms.ValidationError('Requested trip time must be in the future.')
        return requested_for
