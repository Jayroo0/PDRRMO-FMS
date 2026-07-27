from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group, Permission
from django.contrib.contenttypes.models import ContentType
from fleet.models import Vehicle, VehicleType, Part, Issue

class Command(BaseCommand):
    help = 'Populates the entire PDRRMO Fleet Management system with mock production environment data.'

    def handle(self, *args, **options):
        self.stdout.write("--- PHASE 1: Configuring Roles, permissions, and Users ---")
        
        # 1. Setup Security Groups (Roles)
        tech_group, _ = Group.objects.get_or_create(name='Technicians')
        admin_group, _ = Group.objects.get_or_create(name='Fleet Administrators')
        
        # Assign relevant database model permissions to roles
        vehicle_ct = ContentType.objects.get_for_model(Vehicle)
        issue_ct = ContentType.objects.get_for_model(Issue)
        
        view_vehicle = Permission.objects.filter(content_type=vehicle_ct, codename__startswith='view_').first()
        change_issue = Permission.objects.filter(content_type=issue_ct, codename__startswith='change_').first()
        add_issue = Permission.objects.filter(content_type=issue_ct, codename__startswith='add_').first()
        
        if view_vehicle: tech_group.permissions.add(view_vehicle)
        if change_issue: tech_group.permissions.add(change_issue)
        if add_issue:    tech_group.permissions.add(add_issue)

        # 2. Setup System Users
        users_pool = [
            {"username": "tech_maritime1", "email": "maritime.tech1@pdrrmo.gov", "pass": "PdrrmoTech2026!", "group": tech_group, "staff": True},
            {"username": "tech_land1", "email": "land.tech1@pdrrmo.gov", "pass": "PdrrmoTech2026!", "group": tech_group, "staff": True},
            {"username": "fleet_admin", "email": "admin.fleet@pdrrmo.gov", "pass": "PdrrmoAdmin2026!!", "group": admin_group, "staff": True},
        ]
        
        for u_data in users_pool:
            user, created = User.objects.get_or_create(
                username=u_data["username"],
                defaults={
                    "email": u_data["email"],
                    "is_staff": u_data["staff"]
                }
            )
            if created:
                user.set_password(u_data["pass"])
                user.save()
                user.groups.add(u_data["group"])
                self.stdout.write(f"Created user account: {user.username}")
            else:
                self.stdout.write(f"User {user.username} already exists.")

        self.stdout.write("\n--- PHASE 2: Configuring Asset Categorization Types ---")
        
        # 3. Create Multi-Division Vehicle Types
        marine_type, _ = VehicleType.objects.get_or_create(name="MARINE")
        motorcycle_type, _ = VehicleType.objects.get_or_create(name="MOTORCYCLE")
        truck_type, _ = VehicleType.objects.get_or_create(name="TRUCK")
        
        self.stdout.write("Vehicle types initialized (MARINE, MOTORCYCLE, TRUCK).")

        self.stdout.write("\n--- PHASE 3: Configuring Combined Warehouse Inventory Parts ---")
        
        # 4. Supply Parts Room Assets (Both Maritime & Land Mobile parts)
        parts_to_create = [
            # Maritime Components
            {"name": "Outboard Propeller Blades 15-Spline", "quantity": 8},
            {"name": "Marine Engine Impeller (Water Pump)", "quantity": 14},
            {"name": "12V Marine Deep Cycle Battery", "quantity": 4},
            {"name": "Fiberglass Hull Gelcoat Patch Kit", "quantity": 20},
            {"name": "Fuel-Water Separator Filter Element", "quantity": 0}, # Out of stock check case
            
            # Land / Motorcycle Components
            {"name": "Heavy-Duty Motorcycle Drive Chain (428H)", "quantity": 15},
            {"name": "Off-Road Knobby Tire (Rear - 18 inch)", "quantity": 6},
            {"name": "Fully Synthetic Engine Oil 10W-40 (1L)", "quantity": 45},
            {"name": "Hydraulic Brake Pad Set (Front/Rear)", "quantity": 22},
            {"name": "High-Output Halogen Headlight Bulb", "quantity": 18},
        ]

        for p_data in parts_to_create:
            part, created = Part.objects.get_or_create(
                name=p_data["name"],
                defaults={"quantity": p_data["quantity"]}
            )
            if not created:
                part.quantity = p_data["quantity"]
                part.save()
        self.stdout.write(f"Synchronized {len(parts_to_create)} item definitions in parts inventory ledger.")

        self.stdout.write("\n--- PHASE 4: Configuring Global Fleet Registry ---")
        
        # 5. Populate Mixed Fleet Vehicles Array
        vessels_to_create = [
            # Marine Crafts
            {"model_name": "Mercury 250 Speedboat Alpha", "plate_number": "M-250-A1", "type": marine_type, "status": "AVAILABLE"},
            {"model_name": "Yamaha Outboard Rescue Craft B", "plate_number": "Y-RESC-B2", "type": marine_type, "status": "AVAILABLE"},
            {"model_name": "PDRRMO Patrol Boat Charlie", "plate_number": "PDR-PAT-C3", "type": marine_type, "status": "DRY DOCK"},
            
            # Land Division: Motorcycles
            {"model_name": "Kawasaki KLX250 Recon Bike", "plate_number": "PDR-MC-041", "type": motorcycle_type, "status": "AVAILABLE"},
            {"model_name": "Honda CRF250 Rally Emergency Response", "plate_number": "PDR-MC-088", "type": motorcycle_type, "status": "AVAILABLE"},
            {"model_name": "Suzuki DR-Z400 Dual-Sport", "plate_number": "PDR-MC-102", "type": motorcycle_type, "status": "DRY DOCK"},
            
            # Land Division: Heavy Rescue Trucks
            {"model_name": "Isuzu 4x4 High-Clearance Rescue Truck", "plate_number": "PDR-TRK-771", "type": truck_type, "status": "AVAILABLE"},
        ]

        seeded_vehicles = {}
        for v_data in vessels_to_create:
            vehicle, created = Vehicle.objects.get_or_create(
                plate_number=v_data["plate_number"],
                defaults={
                    "model_name": v_data["model_name"],
                    "vehicle_type": v_data["type"],
                    "status": v_data["status"]
                }
            )
            seeded_vehicles[v_data["plate_number"]] = vehicle
        self.stdout.write(f"Registered {len(vessels_to_create)} active motorized assets across multiple divisions.")

        self.stdout.write("\n--- PHASE 5: Dispatching Open Maintenance Backlogs ---")
        
        # 6. Generate Contextual Issues Queue
        issues_to_create = [
            # Seacraft Open Malfunctions
            {
                "plate": "PDR-PAT-C3", 
                "desc": "Portside outboard motor overheating indicator turns on when cruising above 20 knots. Suspected water pump blockage.",
            },
            {
                "plate": "M-250-A1", 
                "desc": "Starboard composite frame shows hairline stress fractures along the fiberglass hull keel lines from rocky shoreline dockings.",
            },
            
            # Motorcycle Open Malfunctions
            {
                "plate": "PDR-MC-102", 
                "desc": "Drive chain stretching exceeding nominal allowances. Needs replacement alongside sprocket inspection following off-road deployment.",
            },
            {
                "plate": "PDR-MC-088", 
                "desc": "Front brake cylinder line losing hydraulic pressure. Lever feels spongy under pressure; needs bleeding and pad wear check.",
            }
        ]

        for i_data in issues_to_create:
            Issue.objects.get_or_create(
                vehicle=seeded_vehicles[i_data["plate"]],
                description=i_data["desc"],
                status="OPEN"
            )

        self.stdout.write(self.style.SUCCESS("\n[SUCCESS] Entire PDRRMO system database populated smoothly! All divisions are operational."))