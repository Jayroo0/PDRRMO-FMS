from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class VehicleType(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name

class Driver(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='driver_profile',
    )
    name = models.CharField(max_length=100, unique=True)
    license_number = models.CharField(max_length=50, blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    # 🛠️ FIX: Corrected __clstr__ typo to the standardized magic method __str__
    def __str__(self):
        return self.name

#-----------------------------------
class VehicleAsset(models.Model):
    ASSET_TYPES = [
        ('LAND', 'Land Transportation'),
        ('SEA', 'Seacraft Vessel'),
    ]
    name = models.CharField(max_length=100) # e.g., "Rescue Truck 01", "Speedboat Delta"
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
    """
    The Command Center Engine that pairs assets to their legally valid operators.
    """
    asset = models.ForeignKey(VehicleAsset, on_delete=models.CASCADE)
    operator = models.ForeignKey(OperatorProfile, on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def clean(self):
        from django.core.exceptions import ValidationError
        
        # Guard Clause: Prevent Land Drivers from operating Seacrafts
        if self.asset.classification == 'SEA' and self.operator.crew_role != 'CAPTAIN':
            raise ValidationError({
                'operator': "Security Exception: Seacrafts require a certified Seacraft Operator/Captain."
            })
            
        # Guard Clause: Prevent Seacraft Skippers from driving Land Vehicles
        if self.asset.classification == 'LAND' and self.operator.crew_role != 'DRIVER':
            raise ValidationError({
                'operator': "Security Exception: Land vehicles require a designated Land Transportation Driver."
            })

    def save(self, *args, **kwargs):
        self.full_clean() # Force validation engine check before write
        super().save(*args, **kwargs)
#-----------------------------------

class Vehicle(models.Model):
    DEPLOYMENT_PURPOSE_CHOICES = [
        ('EMERGENCY_RESPONSE', 'Emergency response'),
        ('MEDICAL_TRANSPORT', 'Medical transport'),
        ('RESCUE_OPERATION', 'Rescue operation'),
        ('OFFICIAL_BUSINESS', 'Official business'),
        ('LOGISTICS_SUPPORT', 'Logistics support'),
        ('OTHER', 'Other'),
    ]
    STATUS_CHOICES = [
        ('OPERATIONAL', 'Operational'),
        ('MAINTENANCE', 'Maintenance'),
        ('DEPLOYED', 'Deployed'),
    ]

    model_name = models.CharField(max_length=100)
    plate_number = models.CharField(max_length=50, unique=True)
    vehicle_type = models.ForeignKey(VehicleType, on_delete=models.CASCADE)
    
    # 🛠️ FIX: Added choices constraint to bind the field parameters safely to your options matrix
    status = models.CharField(
        max_length=50, 
        choices=STATUS_CHOICES, 
        default='OPERATIONAL'
    )
    maintenance_problem = models.CharField(max_length=1000, blank=True)
    
    assigned_driver = models.ForeignKey(
        Driver, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='vehicles'
    )
    deployment_purpose = models.CharField(
        max_length=30,
        choices=DEPLOYMENT_PURPOSE_CHOICES,
        blank=True,
    )
    deployment_destination = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.model_name} ({self.plate_number})"


class VehicleRequest(models.Model):
    PURPOSE_CHOICES = Vehicle.DEPLOYMENT_PURPOSE_CHOICES
    VEHICLE_CATEGORY_CHOICES = [
        ('LAND', 'Land vehicle'),
        ('SEA', 'Seacraft'),
    ]
    STATUS_CHOICES = [
        ('PENDING', 'Pending review'),
        ('APPROVED', 'Approved'),
        ('DECLINED', 'Declined'),
        ('COMPLETED', 'Completed'),
    ]

    requester_name = models.CharField(max_length=150)
    organization = models.CharField(max_length=150, blank=True)
    contact_number = models.CharField(max_length=30)
    purpose = models.CharField(max_length=30, choices=PURPOSE_CHOICES)
    vehicle_category = models.CharField(max_length=4, choices=VEHICLE_CATEGORY_CHOICES)
    requested_for = models.DateTimeField()
    pickup_location = models.CharField(max_length=255)
    destination = models.CharField(max_length=255)
    details = models.TextField()
    assigned_driver = models.ForeignKey(
        Driver,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vehicle_requests',
    )
    assigned_vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vehicle_requests',
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    staff_notes = models.TextField(blank=True)
    tracking_token = models.UUIDField(default=None, unique=True, null=True, blank=True)
    tracking_expires_at = models.DateTimeField(null=True, blank=True)
    current_latitude = models.FloatField(null=True, blank=True)
    current_longitude = models.FloatField(null=True, blank=True)
    location_updated_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-submitted_at']
        verbose_name = 'vehicle request'
        verbose_name_plural = 'vehicle requests'

    def __str__(self):
        return f"{self.get_purpose_display()} - {self.requester_name} ({self.submitted_at:%Y-%m-%d})"

    @property
    def is_tracking_active(self):
        return (
            self.status == 'APPROVED'
            and self.tracking_token is not None
            and self.tracking_expires_at is not None
            and self.tracking_expires_at > timezone.now()
        )


class UnitConditionReport(models.Model):
    CONDITION_CHOICES = [
        ('DAMAGED', 'Damaged'),
        ('DESTROYED', 'Destroyed'),
    ]
    REVIEW_STATUS_CHOICES = [
        ('OPEN', 'Needs review'),
        ('REVIEWED', 'Reviewed'),
    ]

    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='condition_reports',
    )
    driver = models.ForeignKey(
        Driver,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='unit_condition_reports',
    )
    vehicle_request = models.ForeignKey(
        VehicleRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='unit_condition_reports',
    )
    condition = models.CharField(max_length=10, choices=CONDITION_CHOICES)
    description = models.TextField(max_length=2000)
    status = models.CharField(
        max_length=10,
        choices=REVIEW_STATUS_CHOICES,
        default='OPEN',
    )
    reported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-reported_at']
        verbose_name = 'unit condition report'
        verbose_name_plural = 'unit condition reports'

    def __str__(self):
        unit_name = self.vehicle or 'Unassigned vehicle'
        return f'{self.get_condition_display()} report for {unit_name}'


class MaintenanceLog(models.Model):
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name='maintenance_logs',
    )
    service_item = models.CharField(max_length=100)
    details = models.TextField(max_length=2000, blank=True)
    logged_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fleet_maintenance_logs',
    )
    logged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-logged_at']

    def __str__(self):
        return f'{self.service_item} - {self.vehicle}'