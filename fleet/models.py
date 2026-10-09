from django.db import models
from django.contrib.auth.models import User


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

    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='OPERATIONAL')

    maintenance_problem = models.CharField(max_length=1000, blank=True)
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

    def __str__(self):
        return f"{self.model_name} ({self.plate_number})"


class FleetIncident(models.Model):
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