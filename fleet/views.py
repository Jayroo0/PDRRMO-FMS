from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout, authenticate, login
from django.contrib.admin.models import LogEntry, CHANGE, ADDITION 
from django.contrib.contenttypes.models import ContentType          
from django.db import transaction
from django.db.models import Case, When, Value, IntegerField, Q
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from .models import Vehicle, VehicleType, Driver, VehicleAsset, OperatorProfile

# =========================================================================
# SYSTEM SECURITY & AUDIT LOG HELPERS
# =========================================================================

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard_portal:dashboard_portal')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        if not username or not password:
            messages.error(request, "ACCESS DENIED: Username and password are required.")
            return render(request, 'fleet/login.html')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect('dashboard_portal:dashboard_portal')

        messages.error(request, "ACCESS DENIED: Invalid Username or Password.")

    return render(request, 'fleet/login.html')


def custom_user_logout(request):
    if request.method == 'POST':
        logout(request)
        messages.success(request, "You have been logged out of the PDRRMO operations network.")
    return redirect('dashboard_portal:login')

def check_user_role(user, group_name, keywords):
    if user.is_superuser:
        return True
    
    user_group_names = list(user.groups.values_list('name', flat=True))
    if group_name in user_group_names:
        return True
        
    username_lower = user.username.lower()
    if any(kw in username_lower for kw in keywords):
        return True
        
    return False

def log_action_to_admin(request, object_instance, action_flag, change_message):
    LogEntry.objects.create(
        user_id=request.user.id,
        content_type_id=ContentType.objects.get_for_model(object_instance).id,
        object_id=object_instance.id,
        object_repr=str(object_instance),
        action_flag=action_flag,
        change_message=change_message
    )


def add_disposal_reasons(vehicles):
    pending_vehicle_ids = set(
        vehicles.filter(status='PENDING_DISPOSAL').values_list('id', flat=True)
    )
    disposal_reasons = {}
    if pending_vehicle_ids:
        vehicle_content_type = ContentType.objects.get_for_model(Vehicle)
        reason_entries = LogEntry.objects.filter(
            content_type=vehicle_content_type,
            object_id__in=pending_vehicle_ids,
            change_message__contains='Remarks:',
        ).order_by('-action_time').values_list('object_id', 'change_message')

        for vehicle_id, change_message in reason_entries:
            disposal_reasons.setdefault(
                int(vehicle_id),
                change_message.partition('Remarks:')[2].strip(),
            )

    for vehicle in vehicles:
        if vehicle.id in pending_vehicle_ids:
            vehicle.disposal_reason = disposal_reasons.get(vehicle.id, '')
    return vehicles


def seacraft_vehicle_type_filter():
    return (
        Q(vehicle_type__name__iexact='MARINE')
        | Q(vehicle_type__name__iexact='MARITIME')
    )


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


def maintenance_checklist_for_vehicle(vehicle):
    if vehicle.vehicle_type and vehicle.vehicle_type.name.upper() in {'MARINE', 'MARITIME'}:
        return SEACRAFT_MAINTENANCE_CHECKLIST
    return LAND_MAINTENANCE_CHECKLIST


def handle_mechanic_maintenance_action(request, vehicle):
    action_type = request.POST.get('action_type')

    if action_type == 'REPORT_FAULT':
        if vehicle.status not in {'OPERATIONAL', 'DEPLOYED'}:
            messages.error(request, f"{vehicle.model_name} must be operational or deployed before a new maintenance fault can be reported.")
            return

        fault_description = request.POST.get('fault_description', '').strip()
        if not fault_description:
            messages.error(request, "Describe the user-reported fault before moving this asset to maintenance.")
            return
        if len(fault_description) > 1000:
            messages.error(request, "The fault description must be 1,000 characters or fewer.")
            return

        vehicle.status = 'MAINTENANCE'
        vehicle.maintenance_problem = fault_description
        vehicle.assigned_driver = None
        vehicle.deployment_location = None
        vehicle.deployment_purpose = None
        vehicle.deployment_time = None
        vehicle.save()
        log_action_to_admin(
            request,
            vehicle,
            CHANGE,
            f"Reported maintenance fault for {vehicle.model_name}: {fault_description}",
        )
        messages.success(request, f"Fault recorded. {vehicle.model_name} is now in maintenance.")
        return

    if action_type == 'COMPLETE_MAINTENANCE':
        if vehicle.status != 'MAINTENANCE':
            messages.error(request, f"{vehicle.model_name} must be in maintenance before it can be returned to service.")
            return

        checklist = maintenance_checklist_for_vehicle(vehicle)
        checked_items = set(request.POST.getlist('maintenance_checklist'))
        required_items = {item[0] for item in checklist}
        if not required_items.issubset(checked_items):
            messages.error(request, "Complete every maintenance checklist item before returning this asset to operational status.")
            return

        vehicle.status = 'OPERATIONAL'
        vehicle.maintenance_problem = ''
        vehicle.save()
        log_action_to_admin(
            request,
            vehicle,
            CHANGE,
            f"Completed maintenance checklist and returned {vehicle.model_name} to operational status.",
        )
        messages.success(request, f"Checklist complete. {vehicle.model_name} is operational.")
        return

    messages.error(request, "Unsupported mechanic action. Use the fault report or maintenance checklist.")


def seacraft_operator_filter():
    return Q(license_number__istartswith='MAR-')


def vehicle_type_matches_operator(vehicle, driver):
    is_seacraft = vehicle.vehicle_type.name.strip().casefold() in {'marine', 'maritime'}
    is_seacraft_operator = (driver.license_number or '').strip().upper().startswith('MAR-')
    return is_seacraft == is_seacraft_operator


def assign_vehicle_operator(vehicle, driver):
    previous_vehicle = Vehicle.objects.filter(assigned_driver=driver).exclude(pk=vehicle.pk).first()
    if previous_vehicle:
        if previous_vehicle.status not in {'MAINTENANCE', 'PENDING_DISPOSAL'}:
            return previous_vehicle
        previous_vehicle.assigned_driver = None
        previous_vehicle.save(update_fields=['assigned_driver'])

    vehicle.assigned_driver = driver
    return None


# =========================================================================
# 1. HOMEPAGE VIEW
# =========================================================================
def homepage(request):
    all_vehicles = Vehicle.objects.all().select_related('vehicle_type', 'assigned_driver')
    sea_crafts = all_vehicles.filter(seacraft_vehicle_type_filter())
    land_vehicles = all_vehicles.exclude(seacraft_vehicle_type_filter())
    total_fleet = Vehicle.objects.exclude(status='disposal').count()
    land_operational_count = land_vehicles.filter(status='OPERATIONAL').count()
    sea_operational_count = sea_crafts.filter(status='OPERATIONAL').count()
    land_deployed_count = land_vehicles.filter(status='DEPLOYED').count()
    sea_deployed_count = sea_crafts.filter(status='DEPLOYED').count()
    land_maintenance_count = land_vehicles.filter(status='MAINTENANCE').count()
    sea_maintenance_count = sea_crafts.filter(status='MAINTENANCE').count()

    context = {
        'total_fleet': total_fleet,
        'sea_crafts': sea_crafts,
        'land_vehicles': land_vehicles,
        'land_operational_count': land_operational_count,
        'sea_operational_count': sea_operational_count,
        'land_deployed_count': land_deployed_count,
        'sea_deployed_count': sea_deployed_count,
        'land_maintenance_count': land_maintenance_count,
        'sea_maintenance_count': sea_maintenance_count,
        'total_count': all_vehicles.count(),
        'operational_count': all_vehicles.filter(status='OPERATIONAL').count(),
        'maintenance_count': all_vehicles.filter(status='MAINTENANCE').count(),
        'deployed_count': all_vehicles.filter(status='DEPLOYED').count(),
    }
    return render(request, 'fleet/homepage.html', context)


# =========================================================================
# 2. CENTRAL ROUTER VIEW
# =========================================================================
@login_required
def dashboard_router(request):
    user = request.user
    user_group_names = list(user.groups.values_list('name', flat=True))
    user_groups_lower = [g.lower() for g in user_group_names]

    if user.is_superuser or 'superusers' in user_groups_lower:
        return redirect('/admin/')

    group_routing_matrix = {
        'Seacraft Dispatch':     'dashboard_portal:seacraft_dispatch',
        'Maritime_Tech':         'dashboard_portal:seacraft_dashboard',
        'Logistics Officers':    'dashboard_portal:logistics_dashboard',
        'Technicians':           'dashboard_portal:repairman_dashboard',
    }

    for group_name, destination_url in group_routing_matrix.items():
        if group_name in user_group_names:
            return redirect(destination_url)

    for group in user_groups_lower:
        if 'sea' in group or 'craft' in group or 'dispatch' in group:
            return redirect('dashboard_portal:seacraft_dispatch')
        elif 'tech' in group or 'nicians' in group or 'mechanic' in group:
            return redirect('dashboard_portal:repairman_dashboard')
        elif 'log' in group or 'depot' in group or 'manager' in group:
            return redirect('dashboard_portal:logistics_dashboard')

    if user_group_names:
        messages.info(request, f"Welcome {user.username}. Accessing general operations feed.")
        try:
            return redirect('dashboard_portal:homepage')
        except Exception:
            pass 

    return render(request, 'fleet/unassigned_pending.html')


# =========================================================================
# 3. REPAIRMAN DASHBOARD
# =========================================================================
@login_required
def repairman_dashboard(request):
    user = request.user
    is_authorized = check_user_role(
        user,
        'Technicians',
        ['tech', 'technician', 'repair', 'maintenance', 'mechanic']
    )
    
    if not is_authorized:
        messages.error(request, "Access restricted to authorized Repair Technicians.")
        return redirect('homepage')

    if request.method == 'POST':
        vehicle_id = request.POST.get('vehicle_id')
        action_type = request.POST.get('action_type')
        
        if vehicle_id:
            vehicle = get_object_or_404(
                Vehicle.objects.exclude(seacraft_vehicle_type_filter()),
                id=vehicle_id,
            )
            
            if action_type == 'FLAG_DISPOSAL':
                if vehicle.status != 'MAINTENANCE':
                    messages.error(request, f"{vehicle.model_name} must be in maintenance before it can be flagged for disposal.")
                    return redirect('dashboard_portal:repairman_dashboard')

                remarks = request.POST.get('disposal_remarks', '').strip()
                if not remarks:
                    messages.error(request, f"Failure: You must provide a maintenance justification remark to flag {vehicle.model_name} for disposal.")
                    return redirect('dashboard_portal:repairman_dashboard')

                vehicle.status = 'PENDING_DISPOSAL'
                if vehicle.assigned_driver:
                    vehicle.assigned_driver = None
                vehicle.save()
                
                log_action_to_admin(request, vehicle, CHANGE, f"Flagged asset {vehicle.model_name} for disposal from repair workshop. Remarks: {remarks}")
                messages.warning(request, f"{vehicle.model_name} has been routed to Logistics for decommissioning evaluation.")

            elif action_type == 'UNDO_DISPOSAL':
                if vehicle.status != 'PENDING_DISPOSAL':
                    messages.error(request, f"{vehicle.model_name} is not pending disposal.")
                    return redirect('dashboard_portal:repairman_dashboard')

                vehicle.status = 'MAINTENANCE'
                vehicle.save()
                log_action_to_admin(request, vehicle, CHANGE, f"Cancelled disposal request for {vehicle.model_name}; returned to maintenance by workshop.")
                messages.success(request, f"Disposal request for {vehicle.model_name} cancelled; returned to MAINTENANCE.")

            elif action_type == 'UPDATE_DISPOSAL_REASON':
                if vehicle.status != 'PENDING_DISPOSAL':
                    messages.error(request, f"{vehicle.model_name} is not pending disposal.")
                    return redirect('dashboard_portal:repairman_dashboard')

                remarks = request.POST.get('disposal_remarks', '').strip()
                if not remarks:
                    messages.error(request, "A disposal reason is required.")
                    return redirect('dashboard_portal:repairman_dashboard')

                log_action_to_admin(request, vehicle, CHANGE, f"Updated disposal reason for {vehicle.model_name}. Remarks: {remarks}")
                messages.success(request, f"Disposal reason updated for {vehicle.model_name}.")
            
            else:
                handle_mechanic_maintenance_action(request, vehicle)
                    
            return redirect('dashboard_portal:repairman_dashboard')

    vehicles = Vehicle.objects.exclude(
        seacraft_vehicle_type_filter()
    ).select_related(
        'vehicle_type', 'assigned_driver'
    ).order_by(
        Case(
            When(status='OPERATIONAL', then=Value(1)),
            When(status='DEPLOYED', then=Value(2)),
            When(status='MAINTENANCE', then=Value(3)),
            When(status='PENDING_DISPOSAL', then=Value(4)),
            default=Value(5),
            output_field=IntegerField(),
        ),
        'model_name'
    )
    vehicles = add_disposal_reasons(vehicles)
    
    return render(request, 'fleet/repairman_dashboard.html', {
        'vehicles': vehicles,
        'maintenance_checklist': LAND_MAINTENANCE_CHECKLIST,
    })


# =========================================================================
# 4. SEACRAFT DASHBOARD
# =========================================================================
@login_required
def seacraft_dashboard(request):
    user = request.user
    is_authorized = check_user_role(
        user,
        'Maritime_Tech',
        ['maritime', 'sea', 'craft', 'tech', 'dispatch']
    )

    if not is_authorized:
        messages.error(request, "Access restricted to authorized Maritime Operators.")
        return redirect('homepage')

    if request.method == 'POST':
        vehicle_id = request.POST.get('vehicle_id')
        action_type = request.POST.get('action_type')
        
        if vehicle_id:
            vehicle = get_object_or_404(
                Vehicle.objects.filter(seacraft_vehicle_type_filter()),
                id=vehicle_id,
            )
            
            if action_type == 'FLAG_DISPOSAL':
                if vehicle.status != 'MAINTENANCE':
                    messages.error(request, f"{vehicle.model_name} must be in maintenance before it can be flagged for disposal.")
                    return redirect('dashboard_portal:seacraft_dashboard')

                remarks = request.POST.get('disposal_remarks', '').strip()
                if not remarks:
                    messages.error(request, f"Failure: You must provide a justification remark to flag {vehicle.model_name} for disposal.")
                    return redirect('dashboard_portal:seacraft_dashboard')

                vehicle.status = 'PENDING_DISPOSAL'
                if vehicle.assigned_driver:
                    vehicle.assigned_driver = None
                vehicle.save()
                
                log_action_to_admin(request, vehicle, CHANGE, f"Flagged maritime asset {vehicle.model_name} for disposal processing. Remarks: {remarks}")
                messages.warning(request, f"{vehicle.model_name} has been routed to Logistics for disposal confirmation.")

            elif action_type == 'UNDO_DISPOSAL':
                if vehicle.status != 'PENDING_DISPOSAL':
                    messages.error(request, f"{vehicle.model_name} is not pending disposal.")
                    return redirect('dashboard_portal:seacraft_dashboard')

                vehicle.status = 'MAINTENANCE'
                vehicle.save()
                log_action_to_admin(request, vehicle, CHANGE, f"Cancelled disposal request for {vehicle.model_name}; returned to maintenance by maritime workshop.")
                messages.success(request, f"Disposal request for {vehicle.model_name} cancelled; returned to MAINTENANCE.")

            elif action_type == 'UPDATE_DISPOSAL_REASON':
                if vehicle.status != 'PENDING_DISPOSAL':
                    messages.error(request, f"{vehicle.model_name} is not pending disposal.")
                    return redirect('dashboard_portal:seacraft_dashboard')

                remarks = request.POST.get('disposal_remarks', '').strip()
                if not remarks:
                    messages.error(request, "A disposal reason is required.")
                    return redirect('dashboard_portal:seacraft_dashboard')

                log_action_to_admin(request, vehicle, CHANGE, f"Updated disposal reason for {vehicle.model_name}. Remarks: {remarks}")
                messages.success(request, f"Disposal reason updated for {vehicle.model_name}.")
            
            else:
                handle_mechanic_maintenance_action(request, vehicle)
            
            return redirect('dashboard_portal:seacraft_dashboard')

    vehicles = Vehicle.objects.filter(
        seacraft_vehicle_type_filter()
    ).exclude(
        status__in=['ARCHIVED', 'DISPOSED']
    ).select_related(
        'vehicle_type', 'assigned_driver'
    ).order_by(
        Case(
            When(status='OPERATIONAL', then=Value(1)),
            When(status='DEPLOYED', then=Value(2)),
            When(status='MAINTENANCE', then=Value(3)),
            When(status='PENDING_DISPOSAL', then=Value(4)),
            default=Value(5),
            output_field=IntegerField(),
        ),
        'model_name'
    )
    vehicles = add_disposal_reasons(vehicles)

    return render(request, 'fleet/seacraft_dashboard.html', {
        'vehicles': vehicles,
        'maintenance_checklist': SEACRAFT_MAINTENANCE_CHECKLIST,
    })


# =========================================================================
# 5. LOGISTICS DASHBOARD
# =========================================================================
@login_required
def logistics_dashboard(request):
    user = request.user

    if not check_user_role(user, 'Logistics Officers', ['logistics', 'log', 'depot', 'fleet']):
        messages.error(request, "Access restricted to Logistics Depot management accounts.")
        return redirect('homepage')

    if request.method == 'POST':
        action = request.POST.get('action')
        vehicle_id = request.POST.get('vehicle_id')

        # ACTION A: DEPLOY VEHICLE (Requires Location, Purpose, Time, & Operator Validation)
        if action == 'deploy_vehicle':
            vehicle = get_object_or_404(Vehicle, id=vehicle_id)
            if vehicle.status != 'OPERATIONAL':
                messages.error(request, f"'{vehicle.model_name}' must be operational before it can be deployed.")
                return redirect('dashboard_portal:logistics_dashboard')
            
            location = request.POST.get('deployment_location', '').strip()
            purpose = request.POST.get('deployment_purpose', '').strip()
            deploy_time_str = request.POST.get('deployment_time', '').strip()
            driver_id = request.POST.get('driver_id', '').strip()

            if not location or not purpose or not deploy_time_str:
                messages.error(request, "Deployment location, deployment purpose, and deployment time are required to dispatch an asset.")
                return redirect('dashboard_portal:logistics_dashboard')

            parsed_time = parse_datetime(deploy_time_str)
            if parsed_time is None:
                messages.error(request, "Enter a valid deployment date and time.")
                return redirect('dashboard_portal:logistics_dashboard')
            if timezone.is_naive(parsed_time):
                parsed_time = timezone.make_aware(parsed_time, timezone.get_current_timezone())

            if not driver_id:
                messages.error(request, f"DISPATCH DENIED: Personnel operator must be selected prior to deploying '{vehicle.model_name}'.")
                return redirect('dashboard_portal:logistics_dashboard')

            driver_obj = Driver.objects.filter(pk=driver_id, is_active=True).first()
            if driver_obj is None or not vehicle_type_matches_operator(vehicle, driver_obj):
                messages.error(request, "Select an active operator qualified for this vehicle type.")
                return redirect('dashboard_portal:logistics_dashboard')

            with transaction.atomic():
                conflicting_vehicle = assign_vehicle_operator(vehicle, driver_obj)
                if conflicting_vehicle:
                    messages.error(
                        request,
                        f"RESTRICTION: Personnel '{driver_obj.name}' is already assigned to active fleet asset '{conflicting_vehicle.model_name}'.",
                    )
                    return redirect('dashboard_portal:logistics_dashboard')
                vehicle.status = 'DEPLOYED'
                vehicle.deployment_location = location
                vehicle.deployment_purpose = purpose
                vehicle.deployment_time = parsed_time
                vehicle.save()

            log_action_to_admin(
                request, 
                vehicle, 
                CHANGE, 
                f"Deployed asset unit to {location} for '{purpose}' at {parsed_time.strftime('%Y-%m-%d %H:%M')} with operator {vehicle.assigned_driver.name}."
            )
            messages.success(request, f"Asset unit '{vehicle.model_name}' deployed to '{location}' for '{purpose}' with operator '{vehicle.assigned_driver.name}'!")
            return redirect('dashboard_portal:logistics_dashboard')

        # ACTION B: RETURN VEHICLE TO DEPOT BASE
        elif action == 'return_vehicle':
            vehicle = get_object_or_404(Vehicle, id=vehicle_id)
            if vehicle.status != 'DEPLOYED':
                messages.error(request, f"'{vehicle.model_name}' is not currently deployed.")
                return redirect('dashboard_portal:logistics_dashboard')
            vehicle.status = 'OPERATIONAL'
            vehicle.deployment_location = None
            vehicle.deployment_purpose = None
            vehicle.deployment_time = None
            vehicle.save()
            log_action_to_admin(request, vehicle, CHANGE, "Returned asset unit back to operational depot storage.")
            messages.success(request, f"Asset unit {vehicle.model_name} returned to depot!")
            return redirect('dashboard_portal:logistics_dashboard')

        # ACTION C: NEW ASSET REGISTRATION ONBOARDING
        elif action == 'add_vehicle':
            model_name = request.POST.get('model_name')
            plate_number = request.POST.get('plate_number')
            type_id = request.POST.get('vehicle_type')
            
            v_type = get_object_or_404(VehicleType, id=type_id)
            new_asset = Vehicle.objects.create(
                model_name=model_name,
                plate_number=plate_number,
                vehicle_type=v_type,
                status='OPERATIONAL'
            )
            log_action_to_admin(request, new_asset, ADDITION, f"Registered new asset unit '{model_name}' into inventory records.")
            messages.success(request, f"New fleet asset '{model_name}' has been securely registered to the base depot map.")
            return redirect('dashboard_portal:logistics_dashboard')

        # ACTION D: SET/UNSET PERSONNEL OPERATOR
        elif action == 'set_driver':
            vehicle = get_object_or_404(Vehicle, id=vehicle_id)
            if vehicle.status in {'DEPLOYED', 'PENDING_DISPOSAL', 'ARCHIVED'}:
                messages.error(request, f"Operator assignments cannot be changed while '{vehicle.model_name}' is {vehicle.get_status_display().lower()}.")
                return redirect('dashboard_portal:logistics_dashboard')
            driver_id = request.POST.get('driver_id')
            
            if driver_id:  
                driver_obj = Driver.objects.filter(pk=driver_id, is_active=True).first()
                if driver_obj is None or not vehicle_type_matches_operator(vehicle, driver_obj):
                    messages.error(request, "Select an active operator qualified for this vehicle type.")
                    return redirect('dashboard_portal:logistics_dashboard')
                msg = f"Assigned operator {driver_obj.name} to {vehicle.model_name}."
            else:  
                vehicle.assigned_driver = None
                msg = f"Removed driver assignment from asset {vehicle.model_name}."
                
            with transaction.atomic():
                if driver_id:
                    conflicting_vehicle = assign_vehicle_operator(vehicle, driver_obj)
                    if conflicting_vehicle:
                        messages.error(
                            request,
                            f"RESTRICTION: Personnel '{driver_obj.name}' is already assigned to active fleet asset '{conflicting_vehicle.model_name}'.",
                        )
                        return redirect('dashboard_portal:logistics_dashboard')
                vehicle.save()
            log_action_to_admin(request, vehicle, CHANGE, msg)
            messages.success(request, msg)
            return redirect('dashboard_portal:logistics_dashboard')

        # ACTION E: CONFIRM DISPOSAL PIPELINE
        elif action == 'confirm_disposal':
            vessel_to_archive = get_object_or_404(Vehicle, id=vehicle_id)
            if vessel_to_archive.status != 'PENDING_DISPOSAL':
                messages.error(request, f"'{vessel_to_archive.model_name}' is not pending disposal.")
                return redirect('dashboard_portal:logistics_dashboard')
            vessel_to_archive.status = 'ARCHIVED'
            vessel_to_archive.assigned_driver = None
            vessel_to_archive.deployment_location = None
            vessel_to_archive.deployment_purpose = None
            vessel_to_archive.deployment_time = None
            vessel_to_archive.save()
            log_action_to_admin(request, vessel_to_archive, CHANGE, f"Approved and permanently archived asset: {vessel_to_archive.model_name}")
            messages.success(request, f"Asset {vessel_to_archive.model_name} successfully moved to secure archives.")
            return redirect('dashboard_portal:logistics_dashboard')

        # ACTION F: DECLINE DISPOSAL PIPELINE
        elif action == 'decline_disposal':
            vessel_to_repair = get_object_or_404(Vehicle, id=vehicle_id)
            if vessel_to_repair.status != 'PENDING_DISPOSAL':
                messages.error(request, f"'{vessel_to_repair.model_name}' is not pending disposal.")
                return redirect('dashboard_portal:logistics_dashboard')
            vessel_to_repair.status = 'MAINTENANCE'
            vessel_to_repair.save()
            log_action_to_admin(request, vessel_to_repair, CHANGE, f"Rejected disposal request. Returned to maintenance array: {vessel_to_repair.model_name}")
            messages.info(request, f"Disposal declined. {vessel_to_repair.model_name} reverted to MAINTENANCE status.")
            return redirect('dashboard_portal:logistics_dashboard')

        else:
            messages.error(request, "Unsupported logistics dashboard action.")
            return redirect('dashboard_portal:logistics_dashboard')
    all_vehicles = Vehicle.objects.all().select_related('vehicle_type', 'assigned_driver')
    
    status_order = Case(
        When(status='OPERATIONAL', then=Value(1)),
        When(status='DEPLOYED', then=Value(2)),
        When(status='MAINTENANCE', then=Value(3)),
        When(status='PENDING_DISPOSAL', then=Value(4)),
        default=Value(5),
        output_field=IntegerField(),
    )
    land_vehicles = all_vehicles.exclude(
        seacraft_vehicle_type_filter()
    ).exclude(
        status__in=['ARCHIVED', 'DISPOSED']
    ).order_by(status_order, 'model_name')
    sea_crafts = all_vehicles.filter(
        seacraft_vehicle_type_filter()
    ).exclude(
        status__in=['ARCHIVED', 'DISPOSED']
    ).order_by(status_order, 'model_name')

    land_vehicles = add_disposal_reasons(land_vehicles)
    sea_crafts = add_disposal_reasons(sea_crafts)

    land_standby = [v for v in land_vehicles if v.status == 'OPERATIONAL']
    land_deployed = [v for v in land_vehicles if v.status == 'DEPLOYED']
    land_maintenance = [v for v in land_vehicles if v.status in ['MAINTENANCE', 'PENDING_DISPOSAL']]

    sea_standby = [c for c in sea_crafts if c.status == 'OPERATIONAL']
    sea_deployed = [c for c in sea_crafts if c.status == 'DEPLOYED']
    sea_maintenance = [c for c in sea_crafts if c.status in ['MAINTENANCE', 'PENDING_DISPOSAL']]

    all_drivers = Driver.objects.filter(is_active=True)
    land_drivers = all_drivers.exclude(seacraft_operator_filter())
    sea_drivers = all_drivers.filter(seacraft_operator_filter())

    assigned_driver_ids = set(
        Vehicle.objects.filter(assigned_driver__isnull=False).values_list('assigned_driver_id', flat=True)
    )
    
    assigned_driver_map = {
        v.assigned_driver_id: v.model_name for v in Vehicle.objects.filter(assigned_driver__isnull=False)
    }

    types = VehicleType.objects.all()
    
    context = {
        'land_vehicles': land_vehicles, 
        'sea_crafts': sea_crafts, 
        'land_standby': land_standby,
        'land_deployed': land_deployed,
        'land_maintenance': land_maintenance,
        'sea_standby': sea_standby,
        'sea_deployed': sea_deployed,
        'sea_maintenance': sea_maintenance,
        'types': types, 
        'land_drivers': land_drivers,
        'sea_drivers': sea_drivers,
        'assigned_driver_ids': assigned_driver_ids,
        'assigned_driver_map': assigned_driver_map,
    }
    return render(request, 'fleet/logistics_dashboard.html', context)


# =========================================================================
# 6. SEACRAFT DISPATCH VIEW
# =========================================================================
@login_required
def seacraft_dispatch_view(request):
    user = request.user
    if not (
        user.is_superuser
        or user.groups.filter(name="Seacraft Dispatch").exists()
        or any(x in user.username.lower() for x in ["sea", "maritime"])
    ):
        messages.error(request, "Access restricted to authorized Maritime Dispatchers.")
        return redirect("homepage")

    if request.method == "POST":
        action = request.POST.get("action") or request.POST.get("action_type")
        vehicle = get_object_or_404(
            Vehicle.objects.filter(seacraft_vehicle_type_filter()),
            id=request.POST.get("vehicle_id"),
        )

        if action == "FLAG_DISPOSAL":
            if vehicle.status != "MAINTENANCE":
                messages.error(request, f"{vehicle.model_name} must be in maintenance before it can be flagged for disposal.")
                return redirect("dashboard_portal:seacraft_dispatch")
            remarks = request.POST.get("disposal_remarks", "").strip()
            if not remarks:
                messages.error(request, f"Failure: You must provide a justification remark to flag {vehicle.model_name} for disposal.")
                return redirect("dashboard_portal:seacraft_dispatch")

            vehicle.status = "PENDING_DISPOSAL"
            vehicle.assigned_driver = None
            vehicle.deployment_location = None
            vehicle.deployment_purpose = None
            vehicle.deployment_time = None
            vehicle.save(update_fields=[
                "status",
                "assigned_driver",
                "deployment_location",
                "deployment_purpose",
                "deployment_time",
            ])

            log_action_to_admin(request, vehicle, CHANGE, f"Flagged maritime asset {vehicle.model_name} for disposal. Remarks: {remarks}")
            messages.warning(request, f"{vehicle.model_name} has been routed to Logistics for disposal confirmation.")

        elif action in ["DISPATCH_MISSION", "deploy_vehicle"]:
            if vehicle.status != "OPERATIONAL":
                messages.error(request, f"'{vehicle.model_name}' must be operational before it can be deployed.")
                return redirect("dashboard_portal:seacraft_dispatch")

            location = request.POST.get("deployment_location", "").strip()
            purpose = request.POST.get("deployment_purpose", "").strip()
            deploy_time_str = request.POST.get("deployment_time", "").strip()
            driver_id = request.POST.get("driver_id", "").strip()

            if not location or not purpose or not deploy_time_str:
                messages.error(request, "Deployment location, deployment purpose, and deployment time are required to dispatch a vessel.")
                return redirect("dashboard_portal:seacraft_dispatch")

            parsed_time = parse_datetime(deploy_time_str)
            if parsed_time is None:
                messages.error(request, "Enter a valid deployment date and time.")
                return redirect("dashboard_portal:seacraft_dispatch")
            if timezone.is_naive(parsed_time):
                parsed_time = timezone.make_aware(parsed_time, timezone.get_current_timezone())

            driver = Driver.objects.filter(
                pk=driver_id,
                is_active=True,
            ).filter(seacraft_operator_filter()).first()
            if driver is None:
                messages.error(request, "Select an active, qualified seacraft operator before deployment.")
                return redirect("dashboard_portal:seacraft_dispatch")

            with transaction.atomic():
                conflicting_vehicle = assign_vehicle_operator(vehicle, driver)
                if conflicting_vehicle:
                    messages.error(
                        request,
                        f"Personnel operator '{driver.name}' is assigned to active fleet asset '{conflicting_vehicle.model_name}'.",
                    )
                    return redirect("dashboard_portal:seacraft_dispatch")
                vehicle.status = "DEPLOYED"
                vehicle.deployment_location = location
                vehicle.deployment_purpose = purpose
                vehicle.deployment_time = parsed_time
                vehicle.save()

            log_action_to_admin(
                request,
                vehicle,
                CHANGE,
                f"Deployed asset unit to {location} for '{purpose}' at {parsed_time.strftime('%Y-%m-%d %H:%M')} with operator {driver.name}.",
            )
            messages.success(request, f"Vessel '{vehicle.model_name}' deployed to '{location}' for '{purpose}' with operator '{driver.name}'.")

        elif action == "set_driver":
            if vehicle.status in {"DEPLOYED", "PENDING_DISPOSAL", "ARCHIVED"}:
                messages.error(request, f"Operator assignments cannot be changed while '{vehicle.model_name}' is {vehicle.get_status_display().lower()}.")
                return redirect("dashboard_portal:seacraft_dispatch")
            driver_id = request.POST.get("driver_id", "").strip()
            if driver_id:
                driver = Driver.objects.filter(
                    pk=driver_id,
                    is_active=True,
                ).filter(seacraft_operator_filter()).first()
                if driver is None:
                    messages.error(request, "Select an active, qualified seacraft operator.")
                    return redirect("dashboard_portal:seacraft_dispatch")
                msg = f"Operator assignment updated for {vehicle.model_name} to {driver.name}."
            else:
                vehicle.assigned_driver = None
                msg = f"Removed operator assignment from asset {vehicle.model_name}."

            with transaction.atomic():
                if driver_id:
                    conflicting_vehicle = assign_vehicle_operator(vehicle, driver)
                    if conflicting_vehicle:
                        messages.error(
                            request,
                            f"Personnel operator '{driver.name}' is assigned to active fleet asset '{conflicting_vehicle.model_name}'.",
                        )
                        return redirect("dashboard_portal:seacraft_dispatch")
                vehicle.save()
            log_action_to_admin(request, vehicle, CHANGE, msg)
            messages.success(request, msg)

        elif action == "return_vehicle":
            if vehicle.status != "DEPLOYED":
                messages.error(request, f"'{vehicle.model_name}' is not currently deployed.")
                return redirect("dashboard_portal:seacraft_dispatch")
            vehicle.status = "OPERATIONAL"
            vehicle.deployment_location = None
            vehicle.deployment_purpose = None
            vehicle.deployment_time = None
            vehicle.save(update_fields=[
                "status",
                "deployment_location",
                "deployment_purpose",
                "deployment_time",
            ])
            log_action_to_admin(request, vehicle, CHANGE, "Returned asset unit back to operational depot storage.")
            messages.success(request, f"Vessel '{vehicle.model_name}' returned to depot.")

        elif action == "confirm_disposal":
            if vehicle.status != "PENDING_DISPOSAL":
                messages.error(request, f"'{vehicle.model_name}' is not pending disposal.")
                return redirect("dashboard_portal:seacraft_dispatch")
            vehicle.status = "ARCHIVED"
            vehicle.assigned_driver = None
            vehicle.deployment_location = None
            vehicle.deployment_purpose = None
            vehicle.deployment_time = None
            vehicle.save(update_fields=[
                "status",
                "assigned_driver",
                "deployment_location",
                "deployment_purpose",
                "deployment_time",
            ])
            log_action_to_admin(request, vehicle, CHANGE, f"Approved and permanently archived asset: {vehicle.model_name}")
            messages.success(request, f"Asset {vehicle.model_name} successfully moved to secure archives.")

        elif action == "decline_disposal":
            if vehicle.status != "PENDING_DISPOSAL":
                messages.error(request, f"'{vehicle.model_name}' is not pending disposal.")
                return redirect("dashboard_portal:seacraft_dispatch")
            vehicle.status = "MAINTENANCE"
            vehicle.save(update_fields=["status"])
            log_action_to_admin(request, vehicle, CHANGE, f"Rejected disposal request. Returned to maintenance array: {vehicle.model_name}")
            messages.info(request, f"Disposal declined. {vehicle.model_name} reverted to MAINTENANCE status.")

        else:
            messages.error(request, "Unsupported seacraft dispatch action.")

        return redirect("dashboard_portal:seacraft_dispatch")

    all_drivers = Driver.objects.filter(is_active=True)
    sea_drivers = all_drivers.filter(seacraft_operator_filter())

    assigned_driver_ids = set(
        Vehicle.objects.filter(assigned_driver__isnull=False).values_list('assigned_driver_id', flat=True)
    )

    sea_crafts = (
        Vehicle.objects.filter(seacraft_vehicle_type_filter())
        .exclude(status__in=["ARCHIVED", "DISPOSED"])
        .select_related("vehicle_type", "assigned_driver")
        .order_by(
            Case(
                When(status="OPERATIONAL", then=Value(1)),
                When(status="DEPLOYED", then=Value(2)),
                When(status="MAINTENANCE", then=Value(3)),
                When(status="PENDING_DISPOSAL", then=Value(4)),
                default=Value(5),
                output_field=IntegerField(),
            ),
            "model_name",
        )
    )
    sea_crafts = add_disposal_reasons(sea_crafts)

    return render(
        request,
        "fleet/seacraft_dispatch.html",
        {
            "sea_crafts": sea_crafts, 
            "drivers": sea_drivers,
            "assigned_driver_ids": assigned_driver_ids,
        },
    )