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
    
    assigned_driver = models.ForeignKey(
        Driver, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='vehicles'
    )

    def __str__(self):
        return f"{self.model_name} ({self.plate_number})"