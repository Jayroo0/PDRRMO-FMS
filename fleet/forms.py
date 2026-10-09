from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Driver, FleetIncident, Vehicle


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


class FleetIncidentForm(forms.ModelForm):
    occurred_at = forms.DateTimeField(
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S'],
        widget=forms.DateTimeInput(
            attrs={'type': 'datetime-local', 'class': 'form-control'},
            format='%Y-%m-%dT%H:%M',
        ),
    )

    class Meta:
        model = FleetIncident
        fields = (
            'vehicle',
            'incident_type',
            'occurred_at',
            'location',
            'description',
            'damage_details',
            'injury_status',
            'injury_details',
            'witnesses',
            'actions_taken',
            'follow_up_recommendations',
        )
        widgets = {
            'vehicle': forms.Select(attrs={'class': 'form-select'}),
            'incident_type': forms.Select(attrs={'class': 'form-select'}),
            'location': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Where did the incident happen?',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Describe what happened.',
            }),
            'damage_details': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Describe any known damage, or leave blank if none.',
            }),
            'injury_status': forms.Select(attrs={'class': 'form-select'}),
            'injury_details': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Describe injuries or medical assistance required, if any.',
            }),
            'witnesses': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Names or roles of witnesses, if known.',
            }),
            'actions_taken': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'For example, scene secured, assistance called, or asset taken out of service.',
            }),
            'follow_up_recommendations': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Repairs, investigation, or other follow-up required.',
            }),
        }
        labels = {
            'vehicle': 'Fleet asset',
            'incident_type': 'Incident type',
            'occurred_at': 'Date and time',
            'location': 'Incident location',
            'description': 'What happened?',
            'damage_details': 'Damage details (optional)',
            'injury_status': 'Were there injuries?',
            'injury_details': 'Injury / medical assistance details (optional)',
            'witnesses': 'Witnesses (optional)',
            'actions_taken': 'Immediate actions taken (optional)',
            'follow_up_recommendations': 'Follow-up recommendations (optional)',
        }
        help_texts = {
            'description': 'Include relevant details. Do not include unnecessary personal information.',
        }

    def __init__(self, *args, vehicle_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        if vehicle_queryset is not None:
            self.fields['vehicle'].queryset = vehicle_queryset
        self.fields['vehicle'].label_from_instance = (
            lambda vehicle: f'{vehicle.model_name} · {vehicle.plate_number}'
        )
        if not self.is_bound:
            self.initial.setdefault(
                'occurred_at',
                timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
            )

    def clean(self):
        cleaned_data = super().clean()
        injury_status = cleaned_data.get('injury_status')
        injury_details = cleaned_data.get('injury_details', '').strip()
        if injury_status == 'YES' and not injury_details:
            self.add_error(
                'injury_details',
                'Describe the injuries or medical assistance required.',
            )
        return cleaned_data


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
