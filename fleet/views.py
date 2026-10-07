from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout, authenticate, login
from django.contrib.admin.models import LogEntry, CHANGE, ADDITION 
from django.contrib.contenttypes.models import ContentType          
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


# =========================================================================
# 1. HOMEPAGE VIEW
# =========================================================================
def homepage(request):
    all_vehicles = Vehicle.objects.all().select_related('vehicle_type', 'assigned_driver')
    sea_crafts = all_vehicles.filter(vehicle_type__name__iexact='MARINE')
    land_vehicles = all_vehicles.exclude(vehicle_type__name__iexact='MARINE')
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
        action_type = request.POST.get('action_type', 'STATUS_TOGGLE')
        
        if vehicle_id:
            vehicle = get_object_or_404(Vehicle, id=vehicle_id)
            
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
                new_status = request.POST.get('status')
                if vehicle.status == 'PENDING_DISPOSAL':
                    messages.error(request, "Use the cancel disposal action to return this asset to maintenance.")
                elif new_status in ['OPERATIONAL', 'MAINTENANCE']:
                    if new_status == 'MAINTENANCE' and vehicle.assigned_driver:
                        vehicle.assigned_driver = None
                    
                    vehicle.status = new_status
                    vehicle.save()
                    messages.success(request, f"Status for {vehicle.model_name} updated successfully.")
                    
            return redirect('dashboard_portal:repairman_dashboard')

    vehicles = Vehicle.objects.exclude(
        vehicle_type__name__iexact='MARINE'
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
    
    return render(request, 'fleet/repairman_dashboard.html', {'vehicles': vehicles})


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
        action_type = request.POST.get('action_type', 'STATUS_TOGGLE')
        
        if vehicle_id:
            vehicle = get_object_or_404(Vehicle, id=vehicle_id)
            
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
                new_status = request.POST.get('status')
                if vehicle.status == 'PENDING_DISPOSAL':
                    messages.error(request, "Use the cancel disposal action to return this vessel to maintenance.")
                elif new_status in ['OPERATIONAL', 'MAINTENANCE']:
                    if new_status == 'MAINTENANCE' and vehicle.assigned_driver:
                        vehicle.assigned_driver = None
                    
                    vehicle.status = new_status
                    vehicle.save()
                    messages.success(request, f"Status for {vehicle.model_name} updated successfully.")
            
            return redirect('dashboard_portal:seacraft_dashboard')

    vehicles = Vehicle.objects.filter(
        vehicle_type__name__iexact='MARINE'
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

    return render(request, 'fleet/seacraft_dashboard.html', {'vehicles': vehicles})


# =========================================================================
# 5. LOGISTICS DASHBOARD (With Modal Driver Assignment & Location Auto-Suggest)
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

        # ACTION A: DEPLOY VEHICLE (Requires Location, Time, & Personnel Operator Validation)
        if action == 'deploy_vehicle':
            vehicle = get_object_or_404(Vehicle, id=vehicle_id)
            if vehicle.status.upper() == 'MAINTENANCE':
                messages.error(request, f"⚠️ CRITICAL BLOCK: '{vehicle.model_name}' is logged under MAINTENANCE.")
                return redirect('dashboard_portal:logistics_dashboard')
            
            location = request.POST.get('deployment_location', '').strip()
            deploy_time_str = request.POST.get('deployment_time', '').strip()
            driver_id = request.POST.get('driver_id', '').strip()

            if not location or not deploy_time_str:
                messages.error(request, "Deployment location and deployment time are required to dispatch an asset.")
                return redirect('dashboard_portal:logistics_dashboard')

            # Handle Driver Assignment / Driver Switch during deployment
            if driver_id:
                driver_obj = get_object_or_404(Driver, id=driver_id)
                # Check 1 personnel to 1 fleet rule
                conflicting_vehicle = Vehicle.objects.filter(assigned_driver=driver_obj).exclude(id=vehicle.id).first()
                if conflicting_vehicle:
                    messages.error(
                        request, 
                        f"RESTRICTION: Personnel '{driver_obj.name}' is already assigned to fleet asset '{conflicting_vehicle.model_name}'."
                    )
                    return redirect('dashboard_portal:logistics_dashboard')
                vehicle.assigned_driver = driver_obj
            elif not vehicle.assigned_driver:
                messages.error(request, f"DISPATCH DENIED: Personnel operator must be selected prior to deploying '{vehicle.model_name}'.")
                return redirect('dashboard_portal:logistics_dashboard')

            parsed_time = parse_datetime(deploy_time_str)
            if not parsed_time:
                parsed_time = timezone.now()

            vehicle.status = 'DEPLOYED'
            vehicle.deployment_location = location
            vehicle.deployment_time = parsed_time
            vehicle.save()

            log_action_to_admin(
                request, 
                vehicle, 
                CHANGE, 
                f"Deployed asset unit to {location} at {parsed_time.strftime('%Y-%m-%d %H:%M')} with operator {vehicle.assigned_driver.name}."
            )
            messages.success(request, f"Asset unit '{vehicle.model_name}' deployed to '{location}' with operator '{vehicle.assigned_driver.name}'!")
            return redirect('dashboard_portal:logistics_dashboard')

        # ACTION B: RETURN VEHICLE TO DEPOT BASE
        elif action == 'return_vehicle':
            vehicle = get_object_or_404(Vehicle, id=vehicle_id)
            vehicle.status = 'OPERATIONAL'
            vehicle.deployment_location = None
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

        # ACTION D: SET/UNSET PERSONNEL OPERATOR (DRAWER OR QUICK ACTION)
        elif action == 'set_driver':
            vehicle = get_object_or_404(Vehicle, id=vehicle_id)
            driver_id = request.POST.get('driver_id')
            
            if driver_id:  
                driver_obj = get_object_or_404(Driver, id=driver_id)
                conflicting_vehicle = Vehicle.objects.filter(assigned_driver=driver_obj).exclude(id=vehicle.id).first()
                if conflicting_vehicle:
                    messages.error(
                        request, 
                        f"RESTRICTION: Personnel '{driver_obj.name}' is already assigned to fleet asset '{conflicting_vehicle.model_name}'. Personnel can strictly be assigned to 1 fleet asset."
                    )
                    return redirect('dashboard_portal:logistics_dashboard')

                vehicle.assigned_driver = driver_obj
                msg = f"Assigned operator {driver_obj.name} to {vehicle.model_name}."
            else:  
                vehicle.assigned_driver = None
                msg = f"Removed driver assignment from asset {vehicle.model_name}."
                
            vehicle.save()
            log_action_to_admin(request, vehicle, CHANGE, msg)
            messages.success(request, msg)
            return redirect('dashboard_portal:logistics_dashboard')

        # ACTION E: CONFIRM DISPOSAL PIPELINE
        elif action == 'confirm_disposal':
            vessel_to_archive = get_object_or_404(Vehicle, id=vehicle_id)
            vessel_to_archive.status = 'ARCHIVED'
            vessel_to_archive.assigned_driver = None
            vessel_to_archive.deployment_location = None
            vessel_to_archive.deployment_time = None
            vessel_to_archive.save()
            log_action_to_admin(request, vessel_to_archive, CHANGE, f"Approved and permanently archived asset: {vessel_to_archive.model_name}")
            messages.success(request, f"Asset {vessel_to_archive.model_name} successfully moved to secure archives.")
            return redirect('dashboard_portal:logistics_dashboard')

        # ACTION F: DECLINE DISPOSAL PIPELINE
        elif action == 'decline_disposal':
            vessel_to_repair = get_object_or_404(Vehicle, id=vehicle_id)
            vessel_to_repair.status = 'MAINTENANCE'
            vessel_to_repair.save()
            log_action_to_admin(request, vessel_to_repair, CHANGE, f"Rejected disposal request. Returned to maintenance array: {vessel_to_repair.model_name}")
            messages.info(request, f"Disposal declined. {vessel_to_repair.model_name} reverted to MAINTENANCE status.")
            return redirect('dashboard_portal:logistics_dashboard')

    # =========================================================================
    # 🔄 GET WORKFLOW: DATASETS & DRIVER SEGREGATION
    # =========================================================================
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
        vehicle_type__name__iexact='MARINE'
    ).exclude(
        status='ARCHIVED'
    ).order_by(status_order, 'model_name')

    sea_crafts = all_vehicles.filter(
        vehicle_type__name__iexact='MARINE'
    ).exclude(
        status='ARCHIVED'
    ).order_by(status_order, 'model_name')

    land_vehicles = add_disposal_reasons(land_vehicles)
    sea_crafts = add_disposal_reasons(sea_crafts)

    # Tab Data Partitioning
    land_standby = [v for v in land_vehicles if v.status == 'OPERATIONAL']
    land_deployed = [v for v in land_vehicles if v.status == 'DEPLOYED']
    land_maintenance = [v for v in land_vehicles if v.status in ['MAINTENANCE', 'PENDING_DISPOSAL']]

    sea_standby = [c for c in sea_crafts if c.status == 'OPERATIONAL']
    sea_deployed = [c for c in sea_crafts if c.status == 'DEPLOYED']
    sea_maintenance = [c for c in sea_crafts if c.status in ['MAINTENANCE', 'PENDING_DISPOSAL']]

    # Segregate Drivers: Land vs Maritime Operators (MAR- license prefix)
    all_drivers = Driver.objects.filter(is_active=True)
    land_drivers = all_drivers.exclude(license_number__startswith="MAR-")
    sea_drivers = all_drivers.filter(license_number__startswith="MAR-")

    # Mapping of active driver IDs and their assigned fleet models
    assigned_driver_ids = set(
        Vehicle.objects.filter(assigned_driver__isnull=False).values_list('assigned_driver_id', flat=True)
    )
    
    # Map driver ID to assigned vehicle model name for status badges in selection
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

    is_authorized = (
        user.is_superuser
        or user.groups.filter(name="Seacraft Dispatch").exists()
        or any(x in user.username.lower() for x in ["sea", "maritime"])
    )

    if not is_authorized:
        messages.error(request, "Access restricted to authorized Maritime Dispatchers.")
        return redirect("homepage")

    if request.method == "POST":
        action = request.POST.get("action") or request.POST.get("action_type", "STATUS_TOGGLE")
        vehicle_id = request.POST.get("vehicle_id")
        vehicle = get_object_or_404(Vehicle, id=vehicle_id)

        if action == "FLAG_DISPOSAL":
            remarks = request.POST.get("disposal_remarks", "").strip()
            if not remarks:
                messages.error(request, f"Failure: You must provide a justification remark to flag {vehicle.model_name} for disposal.")
                return redirect("dashboard_portal:seacraft_dispatch")

            vehicle.status = "PENDING_DISPOSAL"
            vehicle.assigned_driver = None
            vehicle.save()

            log_action_to_admin(request, vehicle, CHANGE, f"Flagged maritime asset {vehicle.model_name} for disposal. Remarks: {remarks}")
            messages.warning(request, f"{vehicle.model_name} has been routed to Logistics for disposal confirmation.")

        elif action in ["DISPATCH_MISSION", "deploy_vehicle"]:
            if vehicle.status != "OPERATIONAL":
                messages.error(request, f"Dispatch Denied: {vehicle.model_name} must be Operational to deploy.")
            else:
                vehicle.status = "DEPLOYED"
                vehicle.save()
                log_action_to_admin(request, vehicle, CHANGE, f"Dispatched marine vessel {vehicle.model_name} to active tracking grids.")
                messages.success(request, f"Vessel {vehicle.model_name} successfully dispatched!")

        elif action == "set_driver":
            driver_id = request.POST.get("driver_id")
            if driver_id:
                driver = get_object_or_404(Driver, id=driver_id)
                vehicle.assigned_driver = driver
                msg = f"Operator assignment updated for {vehicle.model_name}."
            else:
                vehicle.assigned_driver = None
                msg = f"Removed operator assignment from asset {vehicle.model_name}."

            vehicle.save()
            log_action_to_admin(request, vehicle, CHANGE, msg)
            messages.success(request, msg)

        elif action == "return_vehicle":
            vehicle.status = "OPERATIONAL"
            vehicle.save()
            log_action_to_admin(request, vehicle, CHANGE, f"Returned marine vessel {vehicle.model_name} back to base.")
            messages.success(request, f"{vehicle.model_name} has returned and is flagged as Operational.")

        elif action == "STATUS_TOGGLE":
            new_status = request.POST.get("status")
            if new_status in ["OPERATIONAL", "MAINTENANCE"]:
                if new_status == "MAINTENANCE" and vehicle.assigned_driver:
                    vehicle.assigned_driver = None

                vehicle.status = new_status
                vehicle.save()
                messages.success(request, f"Status for {vehicle.model_name} updated.")

        return redirect("dashboard_portal:seacraft_dispatch")

    busy_driver_ids = Vehicle.objects.filter(
        status="DEPLOYED", assigned_driver__isnull=False
    ).values_list("assigned_driver_id", flat=True)
    
    available_drivers = Driver.objects.filter(
        is_active=True,
        license_number__startswith="MAR-"
    ).exclude(
        id__in=busy_driver_ids
    )

    sea_crafts = (
        Vehicle.objects.filter(
            Q(vehicle_type__name__iexact="marine")
            | Q(vehicle_type__name__iexact="maritime")
        )
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
        {"sea_crafts": sea_crafts, "drivers": available_drivers},
    )