from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class VehicleType(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name


class Driver(models.Model):
    LICENSE_AUTHORITY_CHOICES = [
        ('LTO', 'LTO - Land Transportation Office'),
        ('MARINA', 'MARINA - Maritime Industry Authority'),
    ]

    name = models.CharField(max_length=100, unique=True)
    license_authority = models.CharField(
        max_length=10,
        choices=LICENSE_AUTHORITY_CHOICES,
        default='LTO',
    )
    license_number = models.CharField(max_length=50, blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class VehicleAsset(models.Model):
    ASSET_TYPES = [
        ('LAND', 'Land Transportation'),
        ('SEA', 'Seacraft Vessel'),
    ]
    name = models.CharField(max_length=100)
    classification = models.CharField(max_length=4, choices=ASSET_TYPES)
    plate_or_hull_number = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return f"[{self.classification}] {self.name}"


class OperatorProfile(models.Model):
    ROLE_CHOICES = [
        ('DRIVER', 'Land Transportation Driver'),
        ('CAPTAIN', 'Seacraft Operator / Skipper'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    license_number = models.CharField(max_length=50)
    crew_role = models.CharField(max_length=10, choices=ROLE_CHOICES)

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.get_crew_role_display()})"


class VehicleAssignment(models.Model):
    asset = models.ForeignKey(VehicleAsset, on_delete=models.CASCADE)
    operator = models.ForeignKey(OperatorProfile, on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.asset.classification == 'SEA' and self.operator.crew_role != 'CAPTAIN':
            raise ValidationError({
                'operator': "Security Exception: Seacrafts require a certified Seacraft Operator/Captain."
            })

        if self.asset.classification == 'LAND' and self.operator.crew_role != 'DRIVER':
            raise ValidationError({
                'operator': "Security Exception: Land vehicles require a designated Land Transportation Driver."
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class Vehicle(models.Model):
    SCHEDULED_MAINTENANCE_CHOICES = [
        ('TIRES', 'Tire replacement'),
        ('OIL', 'Oil replacement'),
        ('OTHER', 'Other maintenance'),
    ]

    STATUS_CHOICES = [
        ('OPERATIONAL', 'Operational'),
        ('MAINTENANCE', 'Maintenance'),
        ('DEPLOYED', 'Deployed'),
        ('PENDING_DISPOSAL', 'Pending Disposal'),
        ('ARCHIVED', 'Archived'),
    ]

    model_name = models.CharField(max_length=100)
    plate_number = models.CharField(max_length=50, unique=True)
    vehicle_type = models.ForeignKey(VehicleType, on_delete=models.CASCADE)
    hull_type = models.CharField(max_length=100, blank=True)
    length_m = models.DecimalField(max_digits=7, decimal_places=2, blank=True, null=True)
    make = models.CharField(max_length=100, blank=True)
    model_year = models.PositiveSmallIntegerField(blank=True, null=True)
    color = models.CharField(max_length=50, blank=True)
    odometer_km = models.DecimalField(max_digits=10, decimal_places=1, blank=True, null=True)
    passenger_capacity = models.PositiveIntegerField(blank=True, null=True)
    engine_details = models.CharField(max_length=200, blank=True)
    fuel_type = models.CharField(max_length=50, blank=True)
    registration_expiry = models.DateField(blank=True, null=True)
    inspection_expiry = models.DateField(blank=True, null=True)

    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='OPERATIONAL')

    maintenance_problem = models.CharField(max_length=1000, blank=True)
    maintenance_started_at = models.DateTimeField(null=True, blank=True)
    maintenance_last_assigned_driver = models.CharField(max_length=100, blank=True)
    scheduled_maintenance_type = models.CharField(
        max_length=20,
        choices=SCHEDULED_MAINTENANCE_CHOICES,
        blank=True,
    )
    scheduled_maintenance_date = models.DateField(null=True, blank=True)
    scheduled_maintenance_description = models.CharField(max_length=500, blank=True)
    assigned_driver = models.OneToOneField(
        Driver,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_vehicle',
    )

    # PERSISTENT DEPLOYMENT TRACKING PARAMETERS
    deployment_location = models.CharField(max_length=255, blank=True, null=True)
    deployment_purpose = models.CharField(max_length=255, blank=True, null=True)
    deployment_time = models.DateTimeField(blank=True, null=True)

    def save(self, *args, **kwargs):
        previous = None
        if not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).values(
                'status',
                'maintenance_started_at',
                'maintenance_last_assigned_driver',
                'assigned_driver__name',
            ).first()

        previous_status = previous['status'] if previous else None
        previous_maintenance_started_at = (
            previous['maintenance_started_at'] if previous else None
        )
        previous_maintenance_last_assigned_driver = (
            previous['maintenance_last_assigned_driver'] if previous else ''
        )
        if self.status in {'MAINTENANCE', 'PENDING_DISPOSAL'}:
            if (
                previous_status in {'MAINTENANCE', 'PENDING_DISPOSAL'}
                and previous_maintenance_started_at
            ):
                self.maintenance_started_at = previous_maintenance_started_at
                self.maintenance_last_assigned_driver = (
                    previous_maintenance_last_assigned_driver
                    or previous['assigned_driver__name']
                    or ''
                )
            else:
                self.maintenance_started_at = timezone.now()
                self.maintenance_last_assigned_driver = (
                    previous['assigned_driver__name'] if previous else ''
                ) or ''
        else:
            self.maintenance_started_at = None
            self.maintenance_last_assigned_driver = ''

        update_fields = kwargs.get('update_fields')
        if update_fields is not None and (
            previous is None
            or self.maintenance_started_at != previous_maintenance_started_at
        ):
            update_fields = set(update_fields) | {'maintenance_started_at'}
        if update_fields is not None and (
            previous is None
            or self.maintenance_last_assigned_driver
            != previous_maintenance_last_assigned_driver
        ):
            update_fields = set(update_fields) | {'maintenance_last_assigned_driver'}
        if update_fields is not None:
            kwargs['update_fields'] = update_fields

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.model_name} ({self.plate_number})"


class FleetIncident(models.Model):
    INJURY_STATUS_CHOICES = [
        ('NO', 'No injuries reported'),
        ('YES', 'Injuries reported'),
        ('UNKNOWN', 'Unknown / not confirmed'),
    ]

    INCIDENT_TYPE_CHOICES = [
        ('ACCIDENT', 'Accident'),
        ('COLLISION', 'Collision'),
        ('BREAKDOWN', 'Breakdown during operation'),
        ('DAMAGE', 'Asset or equipment damage'),
        ('SAFETY', 'Safety incident'),
        ('OTHER', 'Other incident'),
    ]

    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.PROTECT,
        related_name='incident_reports',
    )
    incident_type = models.CharField(max_length=20, choices=INCIDENT_TYPE_CHOICES)
    occurred_at = models.DateTimeField()
    location = models.CharField(max_length=255)
    description = models.TextField(max_length=2000)
    damage_details = models.TextField(max_length=2000, blank=True)
    injury_status = models.CharField(
        max_length=10,
        choices=INJURY_STATUS_CHOICES,
        default='UNKNOWN',
    )
    injury_details = models.TextField(max_length=2000, blank=True)
    witnesses = models.TextField(max_length=1000, blank=True)
    actions_taken = models.TextField(max_length=2000, blank=True)
    follow_up_recommendations = models.TextField(max_length=2000, blank=True)
    last_assigned_driver = models.CharField(max_length=100, blank=True)
    reported_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fleet_incident_reports',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-occurred_at', '-pk')

    def __str__(self):
        return f"{self.get_incident_type_display()} - {self.vehicle} ({self.occurred_at:%Y-%m-%d %H:%M})"