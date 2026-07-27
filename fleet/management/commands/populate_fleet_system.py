from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group, Permission
from django.contrib.contenttypes.models import ContentType
from fleet.models import Vehicle, VehicleType

class Command(BaseCommand):
    help = 'Flushes the database, creates system security groups, registers 10 unique users, and seeds the fleet.'

    def handle(self, *args, **options):
        self.stdout.write("--- PHASE 1: Purging Old Asset Registries ---")
        Vehicle.objects.all().delete()
        VehicleType.objects.all().delete()
        
        # We clean out old mock users but keep our main administrative superuser safe
        User.objects.filter(is_superuser=False).delete()
        self.stdout.write("Core tables flushed successfully.")

        self.stdout.write("\n--- PHASE 2: Re-configuring Access Security Roles ---")
        # Initialize permission groups
        tech_group, _ = Group.objects.get_or_create(name='Technicians')
        logistics_group, _ = Group.objects.get_or_create(name='Logistics Officers')
        
        # Dynamic assignment of system views allowances
        vehicle_ct = ContentType.objects.get_for_model(Vehicle)
        change_vehicle = Permission.objects.filter(content_type=vehicle_ct, codename='change_vehicle').first()
        add_vehicle = Permission.objects.filter(content_type=vehicle_ct, codename='add_vehicle').first()
        
        if change_vehicle:
            tech_group.permissions.add(change_vehicle)
            logistics_group.permissions.add(change_vehicle)
        if add_vehicle:
            logistics_group.permissions.add(add_vehicle)

        self.stdout.write("\n--- PHASE 3: Generating 10 Unique System Users ---")
        # 10 completely unique user dictionary objects
        users_pool = [
            # Maintenance Crew Team Accounts
            {"user": "tech_maritime_1", "email": "j.delacruz@pdrrmo.gov.ph", "pass": "PdrrmoTech2026!", "group": tech_group, "first": "Juan", "last": "Dela Cruz"},
            {"user": "tech_maritime_2", "email": "a.bautista@pdrrmo.gov.ph", "pass": "PdrrmoTech2026!", "group": tech_group, "first": "Antonio", "last": "Bautista"},
            {"user": "tech_land_1", "email": "r.santos@pdrrmo.gov.ph", "pass": "PdrrmoTech2026!", "group": tech_group, "first": "Ramir", "last": "Santos"},
            {"user": "tech_land_2", "email": "m.tecson@pdrrmo.gov.ph", "pass": "PdrrmoTech2026!", "group": tech_group, "first": "Manuel", "last": "Tecson"},
            {"user": "tech_heavy_ops", "email": "e.aquino@pdrrmo.gov.ph", "pass": "PdrrmoTech2026!", "group": tech_group, "first": "Eduardo", "last": "Aquino"},
            
            # Logistics Operations Team Accounts
            {"user": "log_officer_north", "email": "v.mendoza@pdrrmo.gov.ph", "pass": "PdrrmoLog2026!!", "group": logistics_group, "first": "Vicente", "last": "Mendoza"},
            {"user": "log_officer_south", "email": "c.reyes@pdrrmo.gov.ph", "pass": "PdrrmoLog2026!!", "group": logistics_group, "first": "Clarissa", "last": "Reyes"},
            {"user": "log_dispatch_hq", "email": "p.soriano@pdrrmo.gov.ph", "pass": "PdrrmoLog2026!!", "group": logistics_group, "first": "Paolo", "last": "Soriano"},
            {"user": "log_analyst", "email": "g.alvarez@pdrrmo.gov.ph", "pass": "PdrrmoLog2026!!", "group": logistics_group, "first": "Grace", "last": "Alvarez"},
            {"user": "fleet_supervisor", "email": "d.guzman@pdrrmo.gov.ph", "pass": "PdrrmoSuper2026!", "group": logistics_group, "first": "Danilo", "last": "Guzman"},
        ]

        for u_data in users_pool:
            user = User.objects.create_user(
                username=u_data["user"],
                email=u_data["email"],
                password=u_data["pass"],
                first_name=u_data["first"],
                last_name=u_data["last"],
                is_staff=True  # Allows access to the Django administrative site
            )
            user.groups.add(u_data["group"])
            self.stdout.write(f"Account Registered: {user.username} ({user.first_name} {user.last_name})")

        self.stdout.write("\n--- PHASE 4: Injecting Asset Registries ---")
        # Domain Classification Types
        marine = VehicleType.objects.create(name="MARINE")
        motorcycle = VehicleType.objects.create(name="MOTORCYCLE")
        truck = VehicleType.objects.create(name="TRUCK")
        ambulance = VehicleType.objects.create(name="AMBULANCE")

    # snippet within fleet/management/commands/populate_fleet_system.py
        fresh_assets = [
            {"model_name": "Mercury 250 Speedboat Alpha", "plate_number": "M-250-A1", "type": marine, "status": "OPERATIONAL", "driver": "Juan Dela Cruz", "phone": "+639123456781"},
            {"model_name": "Yamaha Outboard Rescue Craft B", "plate_number": "Y-RESC-B2", "type": marine, "status": "MAINTENANCE", "driver": "Antonio Bautista", "phone": "+639123456782"},
            {"model_name": "PDRRMO Patrol Boat Charlie", "plate_number": "PDR-PAT-C3", "type": marine, "status": "DEPLOYED", "driver": "None Assigned", "phone": ""},
            {"model_name": "Isuzu 4x4 High Rescue Truck", "plate_number": "PDR-TRK-771", "type": truck, "status": "OPERATIONAL", "driver": "Eduardo Aquino", "phone": "+639123456783"},
            {"model_name": "Toyota Hiace Advance Life Support", "plate_number": "AMB-ALS-02", "type": ambulance, "status": "DEPLOYED", "driver": "Vicente Mendoza", "phone": "+639123456784"}
        ]

        for asset in fresh_assets:
            Vehicle.objects.create(
                model_name=asset["model_name"],
                plate_number=asset["plate_number"],
                vehicle_type=asset["type"],
                status=asset["status"],
                assigned_driver=asset["driver"]
            )

        self.stdout.write(self.style.SUCCESS("\n[SUCCESS] 10 system user accounts and dynamic tracking objects loaded perfectly!"))