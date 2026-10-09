from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Driver


LAND_MAINTENANCE_CHECKLIST = (
    ('repairs_complete', 'Required repairs are complete'),
    ('safety_systems_checked', 'Safety systems have been checked'),
    ('fluids_battery_tires_checked', 'Fluids, battery, and tires have been checked'),
    ('test_run_passed', 'Operational test run passed'),
    ('no_unresolved_issues', 'No unresolved safety or operating issues remain'),
)

SEACRAFT_MAINTENANCE_CHECKLIST = (
    ('repairs_complete', 'Required repairs are complete'),
    ('safety_systems_checked', 'Safety equipment has been checked'),
    ('propulsion_fuel_hull_checked', 'Engine, fuel, bilge, and hull have been checked'),
    ('test_run_passed', 'Sea trial passed'),
    ('no_unresolved_issues', 'No unresolved safety or operating issues remain'),
)


class MaintenanceFaultForm(forms.Form):
    FAULT_TYPE_CHOICES = (
        ('engine', 'Engine / mechanical'),
        ('brakes', 'Brakes'),
        ('tires', 'Tires / wheels'),
        ('electrical', 'Electrical / battery'),
        ('steering', 'Steering / suspension'),
        ('transmission', 'Transmission / drivetrain'),
        ('lights', 'Lights / signals'),
        ('equipment', 'Body / onboard equipment'),
        ('other', 'Other'),
    )

    fault_type = forms.ChoiceField(
        label='Issue type',
        choices=FAULT_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    fault_description = forms.CharField(
        label='Description of issue',
        max_length=1000,
        strip=True,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Describe the issue and when it occurs.',
            'class': 'form-control w-full rounded border border-gray-300 p-2 text-sm',
        }),
    )


class MaintenanceChecklistForm(forms.Form):
    maintenance_checklist = forms.MultipleChoiceField(
        label='Return-to-service checklist',
        choices=(),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'maintenance-checklist'}),
        error_messages={
            'required': 'Complete every maintenance checklist item before returning this asset to operational status.',
        },
    )

    def __init__(self, *args, checklist=LAND_MAINTENANCE_CHECKLIST, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['maintenance_checklist'].choices = checklist
        self.required_checklist = {value for value, _ in checklist}

    def clean_maintenance_checklist(self):
        checked_items = set(self.cleaned_data['maintenance_checklist'])
        if checked_items != self.required_checklist:
            raise ValidationError(
                'Complete every maintenance checklist item before returning this asset to operational status.'
            )
        return checked_items


class ScheduledMaintenanceForm(forms.Form):
    MAINTENANCE_CHOICES = (
        ('TIRES', 'Tire replacement'),
        ('OIL', 'Oil replacement'),
        ('OTHER', 'Other maintenance'),
    )

    maintenance_type = forms.ChoiceField(
        label='Maintenance type',
        choices=MAINTENANCE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    due_date = forms.DateField(
        label='Next replacement / maintenance date',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )
    description = forms.CharField(
        label='Notes (optional)',
        max_length=500,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'For example, tire position or oil specification',
        }),
    )

    def clean_due_date(self):
        due_date = self.cleaned_data['due_date']
        if due_date < timezone.localdate():
            raise ValidationError('Choose today or a future date for the next scheduled maintenance.')
        return due_date


class OperatorDetailsForm(forms.ModelForm):
    OPERATOR_TYPES = (
        ('LAND', 'Land vehicle driver'),
        ('SEA', 'Seacraft operator'),
    )

    operator_type = forms.ChoiceField(
        label='Operator type',
        choices=OPERATOR_TYPES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = Driver
        fields = ('name', 'license_number', 'phone_number')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'license_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter license number',
            }),
            'phone_number': forms.TelInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, allowed_operator_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.allowed_operator_type = allowed_operator_type
        if allowed_operator_type == 'SEA':
            self.fields.pop('operator_type')
        self.fields['name'].label = 'Full name'
        self.fields['license_number'].label = 'License number'
        self.fields['phone_number'].label = 'Phone number'

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if Driver.objects.filter(name__iexact=name).exists():
            raise ValidationError('An operator with this name already exists.')
        return name

    def clean_license_number(self):
        license_number = self.cleaned_data['license_number'].strip()
        if not license_number:
            raise ValidationError('License number is required.')
        return license_number

    def clean(self):
        cleaned_data = super().clean()
        operator_type = self.allowed_operator_type or cleaned_data.get('operator_type')
        if operator_type not in {'LAND', 'SEA'}:
            self.add_error('operator_type', 'Choose land driver or seacraft operator.')
        return cleaned_data

    def save(self, commit=True):
        operator = super().save(commit=False)
        operator_type = self.allowed_operator_type or self.cleaned_data['operator_type']
        operator.license_authority = 'MARINA' if operator_type == 'SEA' else 'LTO'
        if commit:
            operator.save()
            self.save_m2m()
        return operator
