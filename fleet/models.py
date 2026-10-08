from django.db import models
from django.contrib.auth.models import User


class VehicleType(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name


class Driver(models.Model):
    name = models.CharField(max_length=100, unique=True)
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