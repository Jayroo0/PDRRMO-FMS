import csv
from datetime import timedelta
from io import BytesIO
import math
import uuid

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout,authenticate, login
from django.contrib.auth.models import User
from django.contrib.admin.models import LogEntry, CHANGE, ADDITION 
from django.contrib.contenttypes.models import ContentType          
from django.db import transaction
from django.db.models import Case, When, Value, IntegerField, Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .forms import DriverAccountForm, VehicleRequestForm
from .models import (
    Vehicle,
    VehicleType,
    Driver,
    VehicleAsset,
    OperatorProfile,
    VehicleRequest,
    UnitConditionReport,
    MaintenanceLog,
)

MAINTENANCE_RETURN_CHECKLIST = (
    ('repairs_complete', 'Repairs complete'),
    ('safety_systems_checked', 'Safety systems checked'),
    ('fluids_battery_tires_checked', 'Fluids, battery, and tires checked'),
    ('test_run_passed', 'Test run passed'),
    ('no_unresolved_issues', 'No unresolved issues'),
)


def maintenance_return_checklist_is_complete(request):
    submitted_items = set(request.POST.getlist('maintenance_checklist'))
    required_items = {item[0] for item in MAINTENANCE_RETURN_CHECKLIST}
    return required_items.issubset(submitted_items)


# =========================================================================
# SYSTEM SECURITY & AUDIT LOG HELPERS
# =========================================================================
# fleet/views.py

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
    """
    Helper function to securely evaluate if a user belongs to a specific group
    or has a profile keyword in their username.
    """
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


def safe_csv_value(value):
    value = '' if value is None else str(value)
    if value.startswith(('=', '+', '-', '@', '\t', '\r')):
        return f"'{value}"
    return value


def land_dispatch_report_data(selected_datasets):
    report_sections = []

    if 'land_fleet' in selected_datasets:
        rows = [[
            'Record Type',
            'Name / Model',
            'Vehicle Type',
            'Plate Number',
            'Status',
            'Assigned Operator',
        ]]
        land_vehicles = Vehicle.objects.exclude(
            vehicle_type__name__iexact='MARINE',
        ).exclude(
            status__in=['ARCHIVED', 'DISPOSED'],
        ).select_related(
            'vehicle_type', 'assigned_driver',
        ).order_by('model_name')
        rows.extend([
            [
                'Vehicle',
                vehicle.model_name,
                vehicle.vehicle_type.name,
                vehicle.plate_number,
                vehicle.status,
                vehicle.assigned_driver.name if vehicle.assigned_driver else '',
            ]
            for vehicle in land_vehicles
        ])
        report_sections.append(('Land Fleet', rows))

    if 'vehicle_requests' in selected_datasets:
        rows = [[
            'Record Type',
            'Requester',
            'Organization',
            'Contact Number',
            'Status',
            'Purpose',
            'Requested For',
            'Pickup Location',
            'Destination',
            'Assigned Driver',
            'Assigned Vehicle',
            'Request Details',
            'Logistics Notes',
            'Submitted At',
        ]]
        requests = VehicleRequest.objects.filter(
            vehicle_category='LAND',
        ).select_related('assigned_driver', 'assigned_vehicle').order_by('-submitted_at')
        rows.extend([
            [
                'Vehicle Request',
                vehicle_request.requester_name,
                vehicle_request.organization,
                vehicle_request.contact_number,
                vehicle_request.get_status_display(),
                vehicle_request.get_purpose_display(),
                vehicle_request.requested_for.isoformat(),
                vehicle_request.pickup_location,
                vehicle_request.destination,
                vehicle_request.assigned_driver.name if vehicle_request.assigned_driver else '',
                (
                    f'{vehicle_request.assigned_vehicle.model_name} '
                    f'({vehicle_request.assigned_vehicle.plate_number})'
                    if vehicle_request.assigned_vehicle else ''
                ),
                vehicle_request.details,
                vehicle_request.staff_notes,
                vehicle_request.submitted_at.isoformat(),
            ]
            for vehicle_request in requests
        ])
        report_sections.append(('Land Vehicle Requests', rows))

    return report_sections


def generate_csv_report(report_sections):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="land-dispatch-report.csv"'
    writer = csv.writer(response)
    for index, (section_name, rows) in enumerate(report_sections):
        if index:
            writer.writerow([])
        writer.writerow([section_name.upper()])
        for row in rows:
            writer.writerow([safe_csv_value(value) for value in row])
    return response


def generate_excel_report(report_sections):
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    for section_name, rows in report_sections:
        worksheet = workbook.create_sheet(title=section_name[:31])
        for row in rows:
            worksheet.append([safe_csv_value(value) for value in row])
        worksheet.freeze_panes = 'A2'
        worksheet.auto_filter.ref = worksheet.dimensions

    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="land-dispatch-report.xlsx"'
    return response


def generate_pdf_report(report_sections):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    from xml.sax.saxutils import escape

    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=landscape(letter),
        rightMargin=0.4 * inch,
        leftMargin=0.4 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.45 * inch,
    )
    styles = getSampleStyleSheet()
    cell_style = styles['BodyText']
    cell_style.fontSize = 7
    cell_style.leading = 8
    story = [Paragraph('Land Dispatch Report', styles['Title']), Spacer(1, 12)]
    table_width = landscape(letter)[0] - document.leftMargin - document.rightMargin

    for section_name, rows in report_sections:
        story.append(Paragraph(escape(section_name), styles['Heading2']))
        table_data = [
            [Paragraph(escape(str(value)), cell_style) for value in row]
            for row in rows
        ]
        column_width = table_width / len(rows[0])
        table = Table(
            table_data,
            colWidths=[column_width] * len(rows[0]),
            repeatRows=1,
            hAlign='LEFT',
        )
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1A365D')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#CBD5E1')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F1F5F9')]),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.extend([table, Spacer(1, 12)])

    document.build(story)
    response = HttpResponse(output.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="land-dispatch-report.pdf"'
    return response


# =========================================================================
# 1. HOMEPAGE VIEW
# =========================================================================
def landing_page(request):
    return render(request, 'fleet/landing_page.html', {'form': VehicleRequestForm()})


def vehicle_request(request):
    if request.method == 'POST':
        form = VehicleRequestForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Your vehicle request has been submitted for staff review.")
            return redirect('dashboard_portal:landing')
        return render(
            request,
            'fleet/landing_page.html',
            {'form': form, 'open_request_modal': True},
        )
    else:
        form = VehicleRequestForm()

    return render(request, 'fleet/vehicle_request.html', {'form': form})


def homepage(request):
    query = request.GET.get('q', '').strip()
    active_vehicles = Vehicle.objects.exclude(status__in=['ARCHIVED', 'DISPOSED']).select_related('vehicle_type', 'assigned_driver')

    if query:
        active_vehicles = active_vehicles.filter(
            Q(model_name__icontains=query) |
            Q(plate_number__icontains=query) |
            Q(vehicle_type__name__icontains=query) |
            Q(assigned_driver__name__icontains=query)
        )
        search_results = active_vehicles.annotate(
            relevance=Case(
                When(model_name__iexact=query, then=Value(5)),
                When(plate_number__iexact=query, then=Value(5)),
                When(model_name__istartswith=query, then=Value(4)),
                When(plate_number__istartswith=query, then=Value(4)),
                When(vehicle_type__name__iexact=query, then=Value(3)),
                When(assigned_driver__name__icontains=query, then=Value(2)),
                default=Value(1),
                output_field=IntegerField(),
            )
        ).order_by('-relevance', 'model_name')
    else:
        search_results = active_vehicles.none()

    sea_crafts = active_vehicles.filter(vehicle_type__name__iexact='MARINE')
    land_vehicles = active_vehicles.exclude(vehicle_type__name__iexact='MARINE')
    total_fleet = active_vehicles.count()
    land_operational_count = land_vehicles.filter(status='OPERATIONAL').count()
    sea_operational_count = sea_crafts.filter(status='OPERATIONAL').count()
    land_deployed_count = land_vehicles.filter(status='DEPLOYED').count()
    sea_deployed_count = sea_crafts.filter(status='DEPLOYED').count()
    land_maintenance_count = land_vehicles.filter(status='MAINTENANCE').count()
    sea_maintenance_count = sea_crafts.filter(status='MAINTENANCE').count()
    active_trip_requests = VehicleRequest.objects.filter(
        status='APPROVED',
        vehicle_category='LAND',
        tracking_expires_at__gt=timezone.now(),
        tracking_token__isnull=False,
        assigned_driver__isnull=False,
    ).select_related('assigned_vehicle').order_by('-requested_for')
    trips_by_vehicle_id = {}
    for trip in active_trip_requests:
        if trip.assigned_vehicle_id:
            trips_by_vehicle_id.setdefault(trip.assigned_vehicle_id, trip)
    for vehicle in land_vehicles:
        vehicle.active_trip = trips_by_vehicle_id.get(vehicle.id)

    context = {
        'query': query,
        'search_results': search_results,
        'active_trip_requests': active_trip_requests,
        'trip_locations_url': reverse('dashboard_portal:public_trip_locations'),
        'total_fleet': total_fleet,
        'sea_crafts': sea_crafts,
        'land_vehicles': land_vehicles,
        'land_operational_count': land_operational_count,
        'sea_operational_count': sea_operational_count,
        'land_deployed_count': land_deployed_count,
        'sea_deployed_count': sea_deployed_count,
        'land_maintenance_count': land_maintenance_count,
        'sea_maintenance_count': sea_maintenance_count,
        'total_count': total_fleet,
        'operational_count': active_vehicles.filter(status='OPERATIONAL').count(),
        'maintenance_count': active_vehicles.filter(status='MAINTENANCE').count(),
        'deployed_count': active_vehicles.filter(status='DEPLOYED').count(),
    }
    return render(request, 'fleet/homepage.html', context)


def public_trip_locations(request):
    now = timezone.now()
    active_requests = VehicleRequest.objects.filter(
        status='APPROVED',
        vehicle_category='LAND',
        tracking_expires_at__gt=now,
        tracking_token__isnull=False,
        assigned_driver__isnull=False,
    ).order_by('-requested_for')
    response = JsonResponse({
        'trips': [
            {
                'id': vehicle_request.id,
                'vehicle_id': vehicle_request.assigned_vehicle_id,
                'purpose': vehicle_request.get_purpose_display(),
                'pickup': vehicle_request.pickup_location,
                'destination': vehicle_request.destination,
                'latitude': vehicle_request.current_latitude,
                'longitude': vehicle_request.current_longitude,
                'updated_at': (
                    timezone.localtime(vehicle_request.location_updated_at).isoformat()
                    if vehicle_request.location_updated_at else None
                ),
            }
            for vehicle_request in active_requests
        ],
    })
    response['Cache-Control'] = 'no-store'
    return response


@require_http_methods(['GET', 'POST'])
def driver_location_sharing(request, token):
    vehicle_request = get_object_or_404(
        VehicleRequest.objects.select_related('assigned_driver'),
        tracking_token=token,
        status='APPROVED',
        vehicle_category='LAND',
    )
    if not vehicle_request.tracking_expires_at or vehicle_request.tracking_expires_at <= timezone.now():
        return HttpResponse('This location-sharing link has expired.', status=410)

    if request.method == 'POST':
        if request.POST.get('action') == 'report_unit_condition':
            if not vehicle_request.assigned_driver or not vehicle_request.assigned_vehicle:
                return JsonResponse(
                    {'error': 'This trip has no assigned driver or unit.'},
                    status=400,
                )

            condition = request.POST.get('condition', '')
            description = request.POST.get('description', '').strip()
            if condition not in dict(UnitConditionReport.CONDITION_CHOICES):
                messages.error(request, 'Select whether the unit is damaged or destroyed.')
                return redirect('dashboard_portal:driver_location_sharing', token=token)
            if not description or len(description) > 2000:
                messages.error(request, 'Describe the unit condition in 1 to 2000 characters.')
                return redirect('dashboard_portal:driver_location_sharing', token=token)

            UnitConditionReport.objects.create(
                vehicle=vehicle_request.assigned_vehicle,
                driver=vehicle_request.assigned_driver,
                vehicle_request=vehicle_request,
                condition=condition,
                description=description,
            )
            messages.success(
                request,
                'Your unit condition report was sent to Logistics for review. The unit status has not been changed.',
            )
            return redirect('dashboard_portal:driver_location_sharing', token=token)

        try:
            latitude = float(request.POST.get('latitude', ''))
            longitude = float(request.POST.get('longitude', ''))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Valid coordinates are required.'}, status=400)

        if (
            not math.isfinite(latitude)
            or not math.isfinite(longitude)
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
        ):
            return JsonResponse({'error': 'Coordinates are outside valid ranges.'}, status=400)

        vehicle_request.current_latitude = latitude
        vehicle_request.current_longitude = longitude
        vehicle_request.location_updated_at = timezone.now()
        vehicle_request.save(update_fields=[
            'current_latitude',
            'current_longitude',
            'location_updated_at',
        ])
        return JsonResponse({
            'success': True,
            'updated_at': timezone.localtime(vehicle_request.location_updated_at).isoformat(),
        })

    response = render(request, 'fleet/driver_location_sharing.html', {
        'vehicle_request': vehicle_request,
        'tracking_token': token,
        'tracking_url': reverse(
            'dashboard_portal:driver_location_sharing',
            args=[token],
        ),
    })
    response['Cache-Control'] = 'no-store'
    return response


# =========================================================================
# 2. CENTRAL ROUTER VIEW (The Single Portal Gateway)
# =========================================================================
@login_required
def dashboard_router(request):
    user = request.user
    
    # Grab all user group names and lowercase them for flexible matching
    user_group_names = list(user.groups.values_list('name', flat=True))
    user_groups_lower = [g.lower() for g in user_group_names]
    
    print("\n--- PDRRMO DEBUGLOG PORTAL ---")
    print(f"Active User Logging In: {user.username}")
    print(f"Is Staff Status Flag: {user.is_staff}")
    print(f"Detected Database Groups: {user_group_names}")
    print("-------------------------------\n")

    # Superuser check
    if user.is_superuser or 'superusers' in user_groups_lower:
        return redirect('/admin/')

    if Driver.objects.filter(user=user, is_active=True).exists():
        return redirect('dashboard_portal:driver_dashboard')

    # ==========================================================
    # STEP 1: RESOLVE BY EXPLICIT GROUP DESIGNATION (EXACT STRINGS)
    # ==========================================================
    group_routing_matrix = {
        'Seacraft Dispatch':     'dashboard_portal:seacraft_dispatch',
        'Maritime_Tech':         'dashboard_portal:seacraft_dashboard',
        'Logistics Officers':    'dashboard_portal:logistics_dashboard',
        'Technicians': 'dashboard_portal:repairman_dashboard',
    }

    # Evaluate exact case-sensitive matches first for structural integrity
    for group_name, destination_url in group_routing_matrix.items():
        if group_name in user_group_names:
            return redirect(destination_url)

    # ==========================================
    # STEP 2: FLEXIBLE GROUP NAME PATTERN MATCHING (NO USERNAMES)
    # ==========================================
    for group in user_groups_lower:
        if 'sea' in group or 'craft'in group or 'dispatch' in group:
            return redirect('dashboard_portal:seacraft_dispatch')
        elif 'tech' in group or 'nicians' in group or 'mechanic' in group:
            return redirect('dashboard_portal:repairman_dashboard')
        elif 'log' in group or 'depot' in group or 'manager' in group:
            return redirect('dashboard_portal:logistics_dashboard')

    
    # ==========================================
    # STEP 3: SAFEST UNMAPPED ACCOUNT ESCAPE VALVE
    # ==========================================
    if user_group_names:
        messages.info(request, f"Welcome {user.username}. Accessing general operations feed.")
        try:
            return redirect('dashboard_portal:homepage')
        except Exception:
            pass 

    print(f"User {user.username} has no designated functional group assignment. Rendering process standby state.")
    return render(request, 'fleet/unassigned_pending.html')


def dispatch_assignment_view(request, asset_id):
    asset = VehicleAsset.objects.get(id=asset_id)
    
    # Intelligently split available operators based on what asset was selected
    if asset.classification == 'SEA':
        valid_operators = OperatorProfile.objects.filter(crew_role='CAPTAIN')
        context_title = "Select Certified Seacraft Skipper"
    else:
        valid_operators = OperatorProfile.objects.filter(crew_role='DRIVER')
        context_title = "Select Authorized Land Driver"
        
    return render(request, 'dashboard_portal/dispatch.html', {
        'asset': asset,
        'operators': valid_operators,
        'title': context_title
    })


@login_required
def driver_dashboard(request):
    driver = get_object_or_404(Driver, user=request.user, is_active=True)

    if request.method == 'POST':
        if request.POST.get('action') != 'report_unit_condition':
            return HttpResponse('Unsupported driver dashboard action.', status=400)

        vehicle = get_object_or_404(
            Vehicle.objects.select_related('vehicle_type'),
            id=request.POST.get('vehicle_id'),
            assigned_driver=driver,
            status='DEPLOYED',
        )
        condition = request.POST.get('condition', '')
        description = request.POST.get('description', '').strip()
        if condition not in dict(UnitConditionReport.CONDITION_CHOICES):
            messages.error(request, 'Select whether the unit is damaged or destroyed.')
            return redirect('dashboard_portal:driver_dashboard')
        if not description or len(description) > 2000:
            messages.error(request, 'Describe the unit condition in 1 to 2000 characters.')
            return redirect('dashboard_portal:driver_dashboard')

        vehicle_request = VehicleRequest.objects.filter(
            assigned_driver=driver,
            assigned_vehicle=vehicle,
            status='APPROVED',
        ).order_by('-submitted_at').first()
        UnitConditionReport.objects.create(
            vehicle=vehicle,
            driver=driver,
            vehicle_request=vehicle_request,
            condition=condition,
            description=description,
        )
        messages.success(
            request,
            f'Report for {vehicle.model_name} was sent to Logistics for review. Its status was not changed.',
        )
        return redirect('dashboard_portal:driver_dashboard')

    assigned_vehicles = Vehicle.objects.filter(
        assigned_driver=driver,
    ).exclude(
        status__in=['ARCHIVED', 'DISPOSED', 'PENDING_DISPOSAL'],
    ).select_related('vehicle_type').prefetch_related(
        Prefetch(
            'maintenance_logs',
            queryset=MaintenanceLog.objects.order_by('-logged_at')[:5],
            to_attr='recent_maintenance_logs',
        )
    ).order_by('model_name')
    active_requests = VehicleRequest.objects.filter(
        assigned_driver=driver,
        status='APPROVED',
    ).select_related('assigned_vehicle').order_by('-requested_for')
    active_requests_by_vehicle = {}
    for vehicle_request in active_requests:
        if vehicle_request.assigned_vehicle_id:
            active_requests_by_vehicle.setdefault(
                vehicle_request.assigned_vehicle_id,
                vehicle_request,
            )
    for vehicle in assigned_vehicles:
        vehicle.active_request = active_requests_by_vehicle.get(vehicle.id)

    active_tracking_request = VehicleRequest.objects.filter(
        assigned_driver=driver,
        status='APPROVED',
        vehicle_category='LAND',
        tracking_token__isnull=False,
        tracking_expires_at__gt=timezone.now(),
    ).select_related('assigned_vehicle').order_by('-requested_for').first()

    return render(request, 'fleet/driver_dashboard.html', {
        'driver': driver,
        'assigned_vehicles': assigned_vehicles,
        'active_tracking_request': active_tracking_request,
        'tracking_url': (
            reverse(
                'dashboard_portal:driver_location_sharing',
                args=[active_tracking_request.tracking_token],
            )
            if active_tracking_request else ''
        ),
    })


@login_required
def driver_active_trip(request):
    driver = get_object_or_404(Driver, user=request.user, is_active=True)
    vehicle_request = VehicleRequest.objects.filter(
        assigned_driver=driver,
        status='APPROVED',
        vehicle_category='LAND',
        tracking_token__isnull=False,
        tracking_expires_at__gt=timezone.now(),
    ).order_by('-requested_for').first()

    if vehicle_request is None:
        return JsonResponse({'tracking_url': None})

    return JsonResponse({
        'tracking_url': reverse(
            'dashboard_portal:driver_location_sharing',
            args=[vehicle_request.tracking_token],
        ),
    })


# =========================================================================
# 3. GENERAL REPAIRMAN DASHBOARD (Land / Tech Fleet)
# =========================================================================
@login_required
def repairman_dashboard(request):
    user = request.user
    username_lower = user.username.lower()
    user_group_names = list(user.groups.values_list('name', flat=True))

    is_authorized = check_user_role(
        user,
        'Technicians',
        ['tech', 'technician', 'repair', 'maintenance', 'mechanic']
    )
    
    if not is_authorized:
        messages.error(request, "Access restricted to authorized Repair Technicians.")
        return redirect('dashboard_portal:homepage')

    if request.method == 'POST':
        vehicle_id = request.POST.get('vehicle_id')
        action_type = request.POST.get('action_type', '')
        
        if vehicle_id:
            vehicle = get_object_or_404(
                Vehicle.objects.exclude(vehicle_type__name__iexact='MARINE'),
                id=vehicle_id,
            )

            if action_type == 'ADD_MAINTENANCE_LOG':
                if vehicle.status != 'OPERATIONAL':
                    messages.error(request, "Maintenance logs can be added from the operational vehicle tab only.")
                    return redirect('dashboard_portal:repairman_dashboard')

                service_item = request.POST.get('service_item', '').strip()
                details = request.POST.get('details', '').strip()
                if not service_item or len(service_item) > 100 or len(details) > 2000:
                    messages.error(request, "Enter a maintenance item (up to 100 characters) and details under 2000 characters.")
                    return redirect('dashboard_portal:repairman_dashboard')

                MaintenanceLog.objects.create(
                    vehicle=vehicle,
                    service_item=service_item,
                    details=details,
                    logged_by=request.user,
                )
                log_action_to_admin(
                    request,
                    vehicle,
                    CHANGE,
                    f"Maintenance logged: {service_item}. {details}".strip(),
                )
                messages.success(request, f"Maintenance log added for {vehicle.model_name}.")
                return redirect('dashboard_portal:repairman_dashboard')

            if action_type == 'SET_STATUS':
                new_status = request.POST.get('status')
                if vehicle.status not in ['OPERATIONAL', 'MAINTENANCE'] or new_status not in ['OPERATIONAL', 'MAINTENANCE']:
                    messages.error(request, "Only operational and maintenance units can change between those statuses.")
                elif new_status == 'MAINTENANCE':
                    problem = request.POST.get('maintenance_problem', '').strip()
                    if not problem or len(problem) > 1000:
                        messages.error(request, "Describe the problem before sending the vehicle to maintenance (up to 1000 characters).")
                        return redirect('dashboard_portal:repairman_dashboard')
                    vehicle.status = new_status
                    vehicle.maintenance_problem = problem
                    vehicle.save(update_fields=['status', 'maintenance_problem'])
                    messages.success(request, f"{vehicle.model_name} sent to maintenance.")
                else:
                    if not maintenance_return_checklist_is_complete(request):
                        messages.error(request, "Confirm every return-to-service checklist item before marking this vehicle operational.")
                        return redirect('dashboard_portal:repairman_dashboard')
                    vehicle.status = new_status
                    vehicle.maintenance_problem = ''
                    vehicle.save(update_fields=['status', 'maintenance_problem'])
                    messages.success(request, f"{vehicle.model_name} marked as {vehicle.get_status_display()}.")
                return redirect('dashboard_portal:repairman_dashboard')
            
            # ♻️ HANDLE DISPOSAL ACTION TYPE FLAG (WITH REMARKS VALIDATION)
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
                    vehicle.assigned_driver = None  # Force detach operators
                vehicle.save()
                
                # Log to system audit trail trailing the repairman's specific remarks
                log_action_to_admin(request, vehicle, CHANGE, f"Flagged asset {vehicle.model_name} for disposal from repair workshop. Remarks: {remarks}")
                messages.warning(request, f"{vehicle.model_name} has been routed to Logistics for decommissioning evaluation.")

            elif action_type == 'UNDO_DISPOSAL':
                if vehicle.status != 'PENDING_DISPOSAL':
                    messages.error(request, f"{vehicle.model_name} is not pending disposal.")
                    return redirect('dashboard_portal:repairman_dashboard')

                vehicle.status = 'MAINTENANCE'
                vehicle.save()
                log_action_to_admin(
                    request,
                    vehicle,
                    CHANGE,
                    f"Cancelled disposal request for {vehicle.model_name}; returned to maintenance by workshop.",
                )
                messages.success(request, f"Disposal request for {vehicle.model_name} cancelled; returned to MAINTENANCE.")

            elif action_type == 'UPDATE_DISPOSAL_REASON':
                if vehicle.status != 'PENDING_DISPOSAL':
                    messages.error(request, f"{vehicle.model_name} is not pending disposal.")
                    return redirect('dashboard_portal:repairman_dashboard')

                remarks = request.POST.get('disposal_remarks', '').strip()
                if not remarks:
                    messages.error(request, "A disposal reason is required.")
                    return redirect('dashboard_portal:repairman_dashboard')

                log_action_to_admin(
                    request,
                    vehicle,
                    CHANGE,
                    f"Updated disposal reason for {vehicle.model_name}. Remarks: {remarks}",
                )
                messages.success(request, f"Disposal reason updated for {vehicle.model_name}.")
            else:
                messages.error(request, "Unsupported maintenance action.")
                    
            return redirect('dashboard_portal:repairman_dashboard')

    # FIX: Fused the query layout so priority sorting is no longer overwritten
    fleet_status = request.GET.get('status', 'MAINTENANCE_DISPOSAL').upper()
    valid_fleet_statuses = {
        'ALL',
        'OPERATIONAL',
        'DEPLOYED',
        'MAINTENANCE',
        'MAINTENANCE_DISPOSAL',
    }
    if fleet_status not in valid_fleet_statuses:
        fleet_status = 'MAINTENANCE_DISPOSAL'

    vehicles = Vehicle.objects.exclude(
        vehicle_type__name__iexact='MARINE'
    ).select_related(
        'vehicle_type', 'assigned_driver'
    ).prefetch_related(
        Prefetch(
            'maintenance_logs',
            queryset=MaintenanceLog.objects.select_related('logged_by').order_by('-logged_at')[:5],
            to_attr='recent_maintenance_logs',
        )
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
    if fleet_status == 'MAINTENANCE_DISPOSAL':
        vehicles = vehicles.filter(status__in=['MAINTENANCE', 'PENDING_DISPOSAL'])
    elif fleet_status != 'ALL':
        vehicles = vehicles.filter(status=fleet_status)
    vehicles = add_disposal_reasons(vehicles)
    
    return render(request, 'fleet/repairman_dashboard.html', {
        'vehicles': vehicles,
        'fleet_status': fleet_status,
        'fleet_status_tabs': [
            ('MAINTENANCE_DISPOSAL', 'Maintenance & Pending Disposal'),
            ('OPERATIONAL', 'Operational'),
            ('DEPLOYED', 'Deployed'),
            ('ALL', 'All land assets'),
        ],
    })
# =========================================================================
# 4. SPECIALIZED SEACRAFT DASHBOARD (Marine Crafts Only)
# =========================================================================
@login_required
def seacraft_dashboard(request):
    user = request.user
    username_lower = user.username.lower()
    user_group_names = list(user.groups.values_list('name', flat=True))

    is_authorized = check_user_role(
        user,
        'Maritime_Tech',
        ['maritime', 'sea', 'craft', 'tech', 'dispatch']
    )

    if not is_authorized:
        messages.error(request, "Access restricted to authorized Maritime Operators.")
        return redirect('dashboard_portal:homepage')

    if request.method == 'POST':
        vehicle_id = request.POST.get('vehicle_id')
        action_type = request.POST.get('action_type', '')
        
        if vehicle_id:
            vehicle = get_object_or_404(
                Vehicle.objects.filter(vehicle_type__name__iexact='MARINE'),
                id=vehicle_id,
            )

            if action_type == 'ADD_MAINTENANCE_LOG':
                if vehicle.status != 'OPERATIONAL':
                    messages.error(request, "Maintenance logs can be added from the operational seacraft tab only.")
                    return redirect('dashboard_portal:seacraft_dashboard')

                service_item = request.POST.get('service_item', '').strip()
                details = request.POST.get('details', '').strip()
                if not service_item or len(service_item) > 100 or len(details) > 2000:
                    messages.error(request, "Enter a maintenance item (up to 100 characters) and details under 2000 characters.")
                    return redirect('dashboard_portal:seacraft_dashboard')

                MaintenanceLog.objects.create(
                    vehicle=vehicle,
                    service_item=service_item,
                    details=details,
                    logged_by=request.user,
                )
                log_action_to_admin(
                    request,
                    vehicle,
                    CHANGE,
                    f"Maintenance logged: {service_item}. {details}".strip(),
                )
                messages.success(request, f"Maintenance log added for {vehicle.model_name}.")
                return redirect('dashboard_portal:seacraft_dashboard')

            if action_type == 'SET_STATUS':
                new_status = request.POST.get('status')
                if vehicle.status not in ['OPERATIONAL', 'MAINTENANCE'] or new_status not in ['OPERATIONAL', 'MAINTENANCE']:
                    messages.error(request, "Only operational and maintenance vessels can change between those statuses.")
                elif new_status == 'MAINTENANCE':
                    problem = request.POST.get('maintenance_problem', '').strip()
                    if not problem or len(problem) > 1000:
                        messages.error(request, "Describe the problem before sending the seacraft to maintenance (up to 1000 characters).")
                        return redirect('dashboard_portal:seacraft_dashboard')
                    vehicle.status = new_status
                    vehicle.maintenance_problem = problem
                    vehicle.save(update_fields=['status', 'maintenance_problem'])
                    messages.success(request, f"{vehicle.model_name} sent to maintenance.")
                else:
                    if not maintenance_return_checklist_is_complete(request):
                        messages.error(request, "Confirm every return-to-service checklist item before marking this seacraft operational.")
                        return redirect('dashboard_portal:seacraft_dashboard')
                    vehicle.status = new_status
                    vehicle.maintenance_problem = ''
                    vehicle.save(update_fields=['status', 'maintenance_problem'])
                    messages.success(request, f"{vehicle.model_name} marked as {vehicle.get_status_display()}.")
                return redirect('dashboard_portal:seacraft_dashboard')
            
            # ♻️ HANDLE DISPOSAL ACTION TYPE FLAG (WITH REMARKS VALIDATION)
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
                    vehicle.assigned_driver = None  # Force detach operators
                vehicle.save()
                
                # Appends operator remarks directly into your existing administrative audit trail function
                log_action_to_admin(request, vehicle, CHANGE, f"Flagged maritime asset {vehicle.model_name} for disposal processing. Remarks: {remarks}")
                messages.warning(request, f"{vehicle.model_name} has been routed to Logistics for disposal confirmation.")

            elif action_type == 'UNDO_DISPOSAL':
                if vehicle.status != 'PENDING_DISPOSAL':
                    messages.error(request, f"{vehicle.model_name} is not pending disposal.")
                    return redirect('dashboard_portal:seacraft_dashboard')

                vehicle.status = 'MAINTENANCE'
                vehicle.save()
                log_action_to_admin(
                    request,
                    vehicle,
                    CHANGE,
                    f"Cancelled disposal request for {vehicle.model_name}; returned to maintenance by maritime workshop.",
                )
                messages.success(request, f"Disposal request for {vehicle.model_name} cancelled; returned to MAINTENANCE.")

            elif action_type == 'UPDATE_DISPOSAL_REASON':
                if vehicle.status != 'PENDING_DISPOSAL':
                    messages.error(request, f"{vehicle.model_name} is not pending disposal.")
                    return redirect('dashboard_portal:seacraft_dashboard')

                remarks = request.POST.get('disposal_remarks', '').strip()
                if not remarks:
                    messages.error(request, "A disposal reason is required.")
                    return redirect('dashboard_portal:seacraft_dashboard')

                log_action_to_admin(
                    request,
                    vehicle,
                    CHANGE,
                    f"Updated disposal reason for {vehicle.model_name}. Remarks: {remarks}",
                )
                messages.success(request, f"Disposal reason updated for {vehicle.model_name}.")
            
            else:
                messages.error(request, "Unsupported maintenance action.")
            
            return redirect('dashboard_portal:seacraft_dashboard')

    # GET LOGIC: Keep pending disposal vessels visible for workshop review.
    vehicles = Vehicle.objects.filter(
        vehicle_type__name__iexact='MARINE'
    ).exclude(
        status__in=['ARCHIVED', 'DISPOSED']
    ).select_related(
        'vehicle_type', 'assigned_driver'
    ).prefetch_related(
        Prefetch(
            'maintenance_logs',
            queryset=MaintenanceLog.objects.select_related('logged_by').order_by('-logged_at')[:5],
            to_attr='recent_maintenance_logs',
        )
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
# 5. LOGISTICS DASHBOARD (Onboarding & Driver Assignment Matrix)
# =========================================================================
@login_required
def logistics_dashboard(request):
    user = request.user

    if not check_user_role(user, 'Logistics Officers', ['logistics', 'log', 'depot', 'fleet']):
        messages.error(request, "Access restricted to Logistics Depot management accounts.")
        return redirect('dashboard_portal:homepage')

    # 1. Find IDs of drivers currently out on the field in a deployed vehicle
    deployed_driver_ids = Vehicle.objects.filter(
        status='DEPLOYED', 
        assigned_driver__isnull=False
    ).values_list('assigned_driver_id', flat=True)

    active_request_driver_ids = VehicleRequest.objects.filter(
        status='APPROVED',
        assigned_driver__isnull=False,
    ).values_list('assigned_driver_id', flat=True)

    # 2. Fetch base available active drivers who aren't busy
    base_available_drivers = Driver.objects.filter(is_active=True).exclude(
        Q(id__in=deployed_driver_ids) | Q(id__in=active_request_driver_ids)
    )
    
    # Mirroring the seacraft dispatch credential pattern filter:
    # Split into Land Drivers (Exclude MAR-) and Sea Drivers (Startswith MAR-)
    available_sea_drivers = base_available_drivers.filter(license_number__startswith="MAR-")
    available_land_drivers = base_available_drivers.exclude(license_number__startswith="MAR-")
    available_land_request_vehicles = Vehicle.objects.filter(
        status='OPERATIONAL',
    ).exclude(
        vehicle_type__name__iexact='MARINE',
    ).select_related('vehicle_type').order_by('model_name')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        vehicle_id = request.POST.get('vehicle_id')

        if action in ('approve_vehicle_request', 'reject_vehicle_request'):
            request_id = request.POST.get('request_id')
            vehicle_request = get_object_or_404(
                VehicleRequest,
                id=request_id,
                status='PENDING',
                vehicle_category='LAND',
            )
            if action == 'approve_vehicle_request':
                driver_id = request.POST.get('driver_id')
                assigned_driver = available_land_drivers.filter(id=driver_id).first()
                if assigned_driver is None:
                    messages.error(request, 'Select a currently available land driver before approving this request.')
                    return redirect('dashboard_portal:logistics_dashboard')
                assigned_vehicle_id = request.POST.get('assigned_vehicle_id')
                assigned_vehicle = available_land_request_vehicles.filter(
                    id=assigned_vehicle_id,
                ).first()
                if assigned_vehicle is None:
                    messages.error(request, 'Select a currently available land vehicle before approving this request.')
                    return redirect('dashboard_portal:logistics_dashboard')
                tracking_expires_at = vehicle_request.requested_for + timedelta(hours=24)
                if tracking_expires_at <= timezone.now():
                    messages.error(
                        request,
                        'This request’s location-sharing window has expired; it cannot be approved for live tracking.',
                    )
                    return redirect('dashboard_portal:logistics_dashboard')
                vehicle_request.assigned_driver = assigned_driver
                vehicle_request.assigned_vehicle = assigned_vehicle
                vehicle_request.tracking_token = uuid.uuid4()
                vehicle_request.tracking_expires_at = tracking_expires_at
                assigned_vehicle.assigned_driver = assigned_driver
                assigned_vehicle.status = 'DEPLOYED'
                assigned_vehicle.deployment_purpose = vehicle_request.purpose
                assigned_vehicle.deployment_destination = vehicle_request.destination
                assigned_vehicle.save(update_fields=[
                    'assigned_driver',
                    'status',
                    'deployment_purpose',
                    'deployment_destination',
                ])
            else:
                vehicle_request.assigned_driver = None
                vehicle_request.assigned_vehicle = None
                vehicle_request.tracking_token = None
                vehicle_request.tracking_expires_at = None
            vehicle_request.status = (
                'APPROVED' if action == 'approve_vehicle_request' else 'DECLINED'
            )
            vehicle_request.staff_notes = request.POST.get('staff_notes', '').strip()
            vehicle_request.save(update_fields=[
                'status',
                'staff_notes',
                'assigned_driver',
                'assigned_vehicle',
                'tracking_token',
                'tracking_expires_at',
            ])
            log_action_to_admin(
                request,
                vehicle_request,
                CHANGE,
                f"Vehicle request {vehicle_request.status.lower()} by {user.username}.",
            )
            messages.success(
                request,
                f"Request from {vehicle_request.requester_name} was {vehicle_request.status.lower()}.",
            )
            return redirect('dashboard_portal:logistics_dashboard')

        if action == 'create_driver_account':
            available_account_drivers = Driver.objects.filter(
                user__isnull=True,
                is_active=True,
            ).order_by('name')
            form = DriverAccountForm(
                request.POST,
                available_drivers=available_account_drivers,
            )
            if not form.is_valid():
                for field_errors in form.errors.values():
                    for error in field_errors:
                        messages.error(request, error)
                return redirect('dashboard_portal:logistics_dashboard')

            with transaction.atomic():
                linked_driver = None
                if form.cleaned_data['driver_id']:
                    linked_driver = Driver.objects.get(
                        id=form.cleaned_data['driver_id'],
                        user__isnull=True,
                        is_active=True,
                    )
                driver_user = User.objects.create_user(
                    username=form.cleaned_data['username'],
                    password=form.cleaned_data['password'],
                    first_name=(
                        linked_driver.name
                        if linked_driver else form.cleaned_data['name']
                    ),
                )
                if linked_driver:
                    driver = linked_driver
                    driver.user = driver_user
                    driver.save(update_fields=['user'])
                else:
                    driver = Driver.objects.create(
                        user=driver_user,
                        name=form.cleaned_data['name'],
                        license_number=form.cleaned_data['license_number'],
                        phone_number=form.cleaned_data['phone_number'],
                    )

            log_action_to_admin(
                request,
                driver,
                ADDITION,
                f"Created driver account '{driver_user.username}' by {user.username}.",
            )
            messages.success(
                request,
                f"Driver account created for {driver.name}. Give them the username and password securely.",
            )
            return redirect('dashboard_portal:logistics_dashboard')

        if action == 'complete_vehicle_request':
            vehicle_request = get_object_or_404(
                VehicleRequest,
                id=request.POST.get('request_id'),
                status='APPROVED',
                vehicle_category='LAND',
            )
            vehicle_request.status = 'COMPLETED'
            assigned_vehicle = vehicle_request.assigned_vehicle
            if assigned_vehicle and assigned_vehicle.status == 'DEPLOYED':
                assigned_vehicle.status = 'OPERATIONAL'
                assigned_vehicle.deployment_purpose = ''
                assigned_vehicle.deployment_destination = ''
                assigned_vehicle.save(update_fields=[
                    'status',
                    'deployment_purpose',
                    'deployment_destination',
                ])
            vehicle_request.tracking_token = None
            vehicle_request.tracking_expires_at = None
            vehicle_request.current_latitude = None
            vehicle_request.current_longitude = None
            vehicle_request.location_updated_at = None
            vehicle_request.save(update_fields=[
                'status',
                'tracking_token',
                'tracking_expires_at',
                'current_latitude',
                'current_longitude',
                'location_updated_at',
            ])
            log_action_to_admin(
                request,
                vehicle_request,
                CHANGE,
                f"Completed vehicle request by {user.username}; location sharing ended.",
            )
            messages.success(
                request,
                f"Trip for {vehicle_request.requester_name} completed and location sharing ended.",
            )
            return redirect('dashboard_portal:logistics_dashboard')

        if action == 'review_unit_condition_report':
            condition_report = get_object_or_404(
                UnitConditionReport,
                id=request.POST.get('report_id'),
                status='OPEN',
            )
            condition_report.status = 'REVIEWED'
            condition_report.save(update_fields=['status'])
            log_action_to_admin(
                request,
                condition_report,
                CHANGE,
                f"Unit condition report reviewed by {user.username}.",
            )
            messages.success(request, 'Unit condition report marked as reviewed.')
            return redirect('dashboard_portal:logistics_dashboard')

        # Check if this POST request came from the onboarding modal fallback form
        if 'asset_name' in request.POST:
            asset_name = request.POST.get('asset_name')
            asset_type = request.POST.get('asset_type')
            # ... custom fallback creation logic can go here if needed ...
            return redirect('dashboard_portal:logistics_dashboard')

        # ACTION A: DEPLOY VEHICLE OUTBOUND
        if action == 'deploy_vehicle':
            vehicle = get_object_or_404(
                Vehicle.objects.select_related('vehicle_type'),
                id=vehicle_id,
            )
            if vehicle.status != 'OPERATIONAL':
                messages.error(
                    request,
                    f"'{vehicle.model_name}' must be operational before it can be deployed.",
                )
                return redirect('dashboard_portal:logistics_dashboard')
            if VehicleRequest.objects.filter(
                assigned_vehicle=vehicle,
                status='APPROVED',
            ).exists():
                messages.error(
                    request,
                    f"'{vehicle.model_name}' is assigned to an approved request. End that trip from Vehicle Requests.",
                )
                return redirect('dashboard_portal:logistics_dashboard')

            purpose = request.POST.get('deployment_purpose', '').strip()
            destination = request.POST.get('deployment_destination', '').strip()
            if purpose not in dict(Vehicle.DEPLOYMENT_PURPOSE_CHOICES):
                messages.error(request, 'Select a valid purpose before deploying this vehicle.')
                return redirect('dashboard_portal:logistics_dashboard')
            if not destination or len(destination) > 255:
                messages.error(request, 'Enter a destination of 1 to 255 characters before deploying this vehicle.')
                return redirect('dashboard_portal:logistics_dashboard')

            available_drivers = (
                available_sea_drivers
                if vehicle.vehicle_type.name.upper() == 'MARINE'
                else available_land_drivers
            )
            assigned_driver = available_drivers.filter(
                id=request.POST.get('driver_id'),
            ).first()
            if assigned_driver is None:
                messages.error(
                    request,
                    'Select a currently available driver qualified for this vehicle before deployment.',
                )
                return redirect('dashboard_portal:logistics_dashboard')

            vehicle.status = 'DEPLOYED'
            vehicle.assigned_driver = assigned_driver
            vehicle.deployment_purpose = purpose
            vehicle.deployment_destination = destination
            vehicle.save(update_fields=[
                'status',
                'assigned_driver',
                'deployment_purpose',
                'deployment_destination',
            ])
            log_action_to_admin(
                request,
                vehicle,
                CHANGE,
                f"Deployed for {vehicle.get_deployment_purpose_display()} to {destination}.",
            )
            messages.success(request, f"Asset unit {vehicle.model_name} deployed successfully!")
            return redirect('dashboard_portal:logistics_dashboard')

        # ACTION B: RETURN VEHICLE TO DEPOT BASE
        elif action == 'return_vehicle':
            vehicle = get_object_or_404(Vehicle, id=vehicle_id)
            if VehicleRequest.objects.filter(
                assigned_vehicle=vehicle,
                status='APPROVED',
            ).exists():
                messages.error(
                    request,
                    f"'{vehicle.model_name}' is assigned to an approved request. End that trip from Vehicle Requests.",
                )
                return redirect('dashboard_portal:logistics_dashboard')
            if vehicle.status != 'DEPLOYED':
                messages.error(request, f"'{vehicle.model_name}' is not currently deployed.")
                return redirect('dashboard_portal:logistics_dashboard')
            vehicle.status = 'OPERATIONAL'
            vehicle.deployment_purpose = ''
            vehicle.deployment_destination = ''
            vehicle.save(update_fields=[
                'status',
                'deployment_purpose',
                'deployment_destination',
            ])
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

        # ACTION D: PROCESSING INTERACTION FROM DRIVER DROPDOWN SET BUTTONS
        elif action == 'set_driver':
            vehicle = get_object_or_404(Vehicle, id=vehicle_id)
            driver_id = request.POST.get('driver_id')
            
            if driver_id:  
                driver_obj = get_object_or_404(Driver, id=driver_id)
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
            if hasattr(vessel_to_archive, 'is_active'):
                vessel_to_archive.is_active = False
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
    # 🔄 GET WORKFLOW: SPLIT DATA INTO CHANNELS
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
    pending_disposals = all_vehicles.filter(status='PENDING_DISPOSAL')
    pending_vehicle_requests = VehicleRequest.objects.filter(
        status='PENDING',
        vehicle_category='LAND',
    )
    reviewed_vehicle_requests = VehicleRequest.objects.filter(
        vehicle_category='LAND',
    ).exclude(status='PENDING').select_related('assigned_driver', 'assigned_vehicle')
    open_unit_condition_reports = UnitConditionReport.objects.filter(
        status='OPEN',
    ).select_related('vehicle', 'driver', 'vehicle_request')
    land_vehicles = add_disposal_reasons(land_vehicles)
    sea_crafts = add_disposal_reasons(sea_crafts)
    active_tracking_requests = VehicleRequest.objects.filter(
        status='APPROVED',
        vehicle_category='LAND',
        assigned_vehicle__isnull=False,
        assigned_driver__isnull=False,
        tracking_token__isnull=False,
        tracking_expires_at__gt=timezone.now(),
    ).select_related('assigned_vehicle').order_by('-requested_for')
    tracking_request_by_vehicle_id = {}
    for vehicle_request in active_tracking_requests:
        tracking_request_by_vehicle_id.setdefault(
            vehicle_request.assigned_vehicle_id,
            vehicle_request,
        )
    for vehicle in land_vehicles:
        vehicle.active_tracking_request = tracking_request_by_vehicle_id.get(vehicle.id)
    
    types = VehicleType.objects.all()
    
    context = {
        'land_vehicles': land_vehicles, 
        'sea_crafts': sea_crafts, 
        'types': types, 
        'drivers': base_available_drivers, # Preserved to avoid breaking general references
        'land_drivers': available_land_drivers, # Added for clean segregation in land tables
        'sea_drivers': available_sea_drivers,   # Added for mirrored MAR- filter validation in marine tables
        'pending_disposals': pending_disposals,
        'pending_vehicle_requests': pending_vehicle_requests,
        'reviewed_vehicle_requests': reviewed_vehicle_requests,
        'available_land_request_drivers': available_land_drivers,
        'available_land_request_vehicles': available_land_request_vehicles,
        'deployment_purpose_choices': Vehicle.DEPLOYMENT_PURPOSE_CHOICES,
        'open_unit_condition_reports': open_unit_condition_reports,
        'drivers_without_accounts': Driver.objects.filter(
            user__isnull=True,
            is_active=True,
        ).order_by('name'),
        'trip_locations_url': reverse('dashboard_portal:public_trip_locations'),
    }
    return render(request, 'fleet/logistics_dashboard.html', context)


@login_required
def land_dispatch_report(request):
    user = request.user
    if not check_user_role(user, 'Logistics Officers', ['logistics', 'log', 'depot', 'fleet']):
        messages.error(request, "Access restricted to authorized Logistics Depot management accounts.")
        return redirect('dashboard_portal:homepage')

    selected_datasets = set(request.GET.getlist('dataset'))
    available_datasets = {'land_fleet', 'vehicle_requests'}
    if not selected_datasets or not selected_datasets.issubset(available_datasets):
        return HttpResponse(
            'Select at least one valid report dataset.',
            status=400,
            content_type='text/plain; charset=utf-8',
        )

    report_format = request.GET.get('format')
    if report_format not in {'csv', 'pdf', 'excel'}:
        return HttpResponse(
            'Select a valid report format.',
            status=400,
            content_type='text/plain; charset=utf-8',
        )

    report_sections = land_dispatch_report_data(selected_datasets)
    if report_format == 'csv':
        return generate_csv_report(report_sections)
    if report_format == 'excel':
        return generate_excel_report(report_sections)
    return generate_pdf_report(report_sections)


@login_required
def seacraft_dispatch_view(request):
    user = request.user

    # 1. Simplified Authorization Check
    # Extracted logic cleanly to avoid side effects during mid-session state evaluations
    is_authorized = (
        user.is_superuser
        or user.groups.filter(name="Seacraft Dispatch").exists()
        or any(x in user.username.lower() for x in ["sea", "maritime"])
    )

    if not is_authorized:
        messages.error(
            request, "Access restricted to authorized Maritime Dispatchers."
        )
        return redirect("homepage")

    # 2. POST Workflow (Actions Processing)
    if request.method == "POST":
        action = request.POST.get("action") or request.POST.get("action_type", "")
        vehicle_id = request.POST.get("vehicle_id")
        vehicle = get_object_or_404(
            Vehicle.objects.filter(
                Q(vehicle_type__name__iexact="marine")
                | Q(vehicle_type__name__iexact="maritime")
            ),
            id=vehicle_id,
        )

        # ACTION: FLAG_DISPOSAL
        if action == "FLAG_DISPOSAL":
            remarks = request.POST.get("disposal_remarks", "").strip()
            if not remarks:
                messages.error(
                    request,
                    f"Failure: You must provide a justification remark to flag {vehicle.model_name} for disposal.",
                )
                return redirect("dashboard_portal:seacraft_dispatch")

            vehicle.status = "PENDING_DISPOSAL"
            vehicle.assigned_driver = None  # Detach operator on decommissioning pipeline
            vehicle.save()

            log_action_to_admin(
                request,
                vehicle,
                CHANGE,
                f"Flagged maritime asset {vehicle.model_name} for disposal. Remarks: {remarks}",
            )
            messages.warning(
                request,
                f"{vehicle.model_name} has been routed to Logistics for disposal confirmation.",
            )

        # ACTION: DEPLOY VEHICLE
        elif action in ["DISPATCH_MISSION", "deploy_vehicle"]:
            if vehicle.status != "OPERATIONAL":
                messages.error(
                    request,
                    f"Dispatch Denied: {vehicle.model_name} must be Operational to deploy.",
                )
            else:
                vehicle.status = "DEPLOYED"
                vehicle.save()
                log_action_to_admin(
                    request,
                    vehicle,
                    CHANGE,
                    f"Dispatched marine vessel {vehicle.model_name} to active tracking grids.",
                )
                messages.success(
                    request,
                    f"Vessel {vehicle.model_name} successfully dispatched!",
                )

        # ACTION: SET OPERATOR ASSIGNMENT
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

        # ACTION: RETURN VEHICLE TO BASE
        elif action == "complete_maintenance":
            if vehicle.status != "MAINTENANCE":
                messages.error(request, f"{vehicle.model_name} is not in maintenance.")
            elif not maintenance_return_checklist_is_complete(request):
                messages.error(request, "Confirm every return-to-service checklist item before marking this seacraft operational.")
            else:
                vehicle.status = "OPERATIONAL"
                vehicle.maintenance_problem = ""
                vehicle.save(update_fields=["status", "maintenance_problem"])
                log_action_to_admin(
                    request,
                    vehicle,
                    CHANGE,
                    f"Maintenance completed for {vehicle.model_name}; return-to-service checklist confirmed.",
                )
                messages.success(request, f"{vehicle.model_name} passed its return-to-service checklist and is operational.")

        elif action == "return_vehicle":
            if vehicle.status != "DEPLOYED":
                messages.error(request, f"{vehicle.model_name} is not currently deployed.")
                return redirect("dashboard_portal:seacraft_dispatch")
            vehicle.status = "OPERATIONAL"
            vehicle.maintenance_problem = ""
            vehicle.save()
            log_action_to_admin(
                request,
                vehicle,
                CHANGE,
                f"Returned marine vessel {vehicle.model_name} back to base.",
            )
            messages.success(
                request,
                f"{vehicle.model_name} has returned and is flagged as Operational.",
            )

        else:
            messages.error(request, "Unsupported seacraft dispatch action.")

        return redirect("dashboard_portal:seacraft_dispatch")

    # 3. GET Workflow (Render Data Partitioning)
    busy_driver_ids = Vehicle.objects.filter(
        status="DEPLOYED", assigned_driver__isnull=False
    ).values_list("assigned_driver_id", flat=True)
    
    # UPDATED: Added a filter to ensure only drivers with a maritime/seacraft credential pattern are queried
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
    maintenance_crafts = [
        craft for craft in sea_crafts
        if craft.status == "MAINTENANCE"
    ]

    return render(
        request,
        "fleet/seacraft_dispatch.html",
        {
            "sea_crafts": sea_crafts,
            "maintenance_crafts": maintenance_crafts,
            "drivers": available_drivers,
        },
    )