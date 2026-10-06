from datetime import datetime, timedelta
from io import BytesIO
import uuid

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from .models import (
    Driver,
    MaintenanceLog,
    UnitConditionReport,
    Vehicle,
    VehicleRequest,
    VehicleType,
)


class LoginViewTests(TestCase):
    def test_login_page_renders_without_authenticating_on_get(self):
        response = self.client.get(reverse('dashboard_portal:login'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Fleet Operations Center')
        self.assertNotContains(response, 'ACCESS DENIED: Invalid Username or Password.')

    def test_login_page_shows_error_for_invalid_credentials(self):
        response = self.client.post(
            reverse('dashboard_portal:login'),
            {'username': 'unknown-user', 'password': 'wrong-password'},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ACCESS DENIED: Invalid Username or Password.')

    def test_logistics_dashboard_allows_non_staff_user_in_logistics_group(self):
        group = Group.objects.create(name='Logistics Officers')
        user = User.objects.create_user(username='logistics_user', password='SecurePass123!')
        user.groups.add(group)
        user.is_staff = False
        user.save()

        self.client.force_login(user)
        response = self.client.get(reverse('dashboard_portal:logistics_dashboard'))

        self.assertEqual(response.status_code, 200)

    def test_driver_login_routes_to_driver_dashboard(self):
        driver_user = User.objects.create_user(
            username='phone_driver',
            password='DriverSecurePass!2026',
        )
        driver = Driver.objects.create(
            user=driver_user,
            name='Phone Driver',
            license_number='LAND-007',
        )
        vehicle_type = VehicleType.objects.create(name='Driver Test Truck')
        Vehicle.objects.create(
            model_name='Assigned Rescue Unit',
            plate_number='DRIVER-007',
            vehicle_type=vehicle_type,
            status='DEPLOYED',
            assigned_driver=driver,
            deployment_purpose='RESCUE_OPERATION',
            deployment_destination='North District',
        )

        response = self.client.post(
            reverse('dashboard_portal:login'),
            {'username': 'phone_driver', 'password': 'DriverSecurePass!2026'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('dashboard_portal:dashboard_portal'))
        dashboard_response = self.client.get(reverse('dashboard_portal:dashboard_portal'))
        self.assertRedirects(
            dashboard_response,
            reverse('dashboard_portal:driver_dashboard'),
        )
        dashboard_response = self.client.get(reverse('dashboard_portal:driver_dashboard'))
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertContains(dashboard_response, 'Assigned Rescue Unit')
        self.assertContains(dashboard_response, 'North District')

    def test_logistics_can_create_driver_account_and_link_existing_driver(self):
        logistics_group = Group.objects.create(name='Logistics Officers')
        logistics_user = User.objects.create_user(
            username='driver_account_manager',
            password='SecurePass123!',
        )
        logistics_user.groups.add(logistics_group)
        self.client.force_login(logistics_user)
        existing_driver = Driver.objects.create(
            name='Existing Unlinked Driver',
            license_number='LAND-008',
        )

        response = self.client.post(
            reverse('dashboard_portal:logistics_dashboard'),
            {
                'action': 'create_driver_account',
                'driver_id': str(existing_driver.id),
                'username': 'existing_driver_login',
                'password': 'DriverSecurePass!2026',
                'name': '',
                'license_number': '',
                'phone_number': '',
            },
        )

        self.assertRedirects(response, reverse('dashboard_portal:logistics_dashboard'))
        existing_driver.refresh_from_db()
        self.assertEqual(existing_driver.user.username, 'existing_driver_login')
        self.assertTrue(existing_driver.user.check_password('DriverSecurePass!2026'))

    def test_driver_dashboard_reports_only_their_assigned_deployed_unit(self):
        driver_user = User.objects.create_user(
            username='reporting_driver',
            password='DriverSecurePass!2026',
        )
        driver = Driver.objects.create(
            user=driver_user,
            name='Reporting Driver',
        )
        vehicle_type = VehicleType.objects.create(name='Report Test Vehicle')
        vehicle = Vehicle.objects.create(
            model_name='Reporting Unit',
            plate_number='REPORT-001',
            vehicle_type=vehicle_type,
            status='DEPLOYED',
            assigned_driver=driver,
        )
        self.client.force_login(driver_user)

        response = self.client.post(
            reverse('dashboard_portal:driver_dashboard'),
            {
                'action': 'report_unit_condition',
                'vehicle_id': vehicle.id,
                'condition': 'DESTROYED',
                'description': 'Unit was destroyed during the operation.',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(UnitConditionReport.objects.count(), 1)
        report = UnitConditionReport.objects.get()
        self.assertEqual(report.vehicle, vehicle)
        self.assertEqual(report.driver, driver)
        self.assertEqual(report.condition, 'DESTROYED')
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, 'DEPLOYED')

    def test_driver_dashboard_shows_recent_logs_for_assigned_vehicle_in_maintenance(self):
        driver_user = User.objects.create_user(
            username='maintenance_history_driver',
            password='DriverSecurePass!2026',
        )
        driver = Driver.objects.create(user=driver_user, name='Maintenance History Driver')
        vehicle_type = VehicleType.objects.create(name='Maintenance History Truck')
        vehicle = Vehicle.objects.create(
            model_name='Assigned Vehicle In Workshop',
            plate_number='MAINT-HIST-01',
            vehicle_type=vehicle_type,
            status='MAINTENANCE',
            assigned_driver=driver,
        )
        MaintenanceLog.objects.create(
            vehicle=vehicle,
            service_item='Oil change',
            details='Replaced engine oil and filter.',
        )
        self.client.force_login(driver_user)

        response = self.client.get(reverse('dashboard_portal:driver_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Assigned Vehicle In Workshop')
        self.assertContains(response, 'Oil change')
        self.assertContains(response, 'Replaced engine oil and filter.')


class PublicServicesTests(TestCase):
    def test_landing_page_offers_request_public_view_and_login(self):
        response = self.client.get(reverse('dashboard_portal:landing'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-bs-target="#vehicleRequestModal"')
        self.assertContains(response, reverse('dashboard_portal:vehicle_request'))
        self.assertContains(response, 'id="vehicleRequestModal"')
        self.assertContains(response, reverse('dashboard_portal:homepage'))
        self.assertContains(response, reverse('dashboard_portal:login'))

    def test_invalid_vehicle_request_reopens_landing_modal_with_errors(self):
        response = self.client.post(
            reverse('dashboard_portal:vehicle_request'),
            {'requester_name': '', 'contact_number': 'invalid'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'bootstrap.Modal.getOrCreateInstance')
        self.assertContains(response, 'id="vehicleRequestModal"')
        self.assertEqual(VehicleRequest.objects.count(), 0)

    def test_vehicle_request_submission_is_stored_for_staff_review(self):
        response = self.client.post(
            reverse('dashboard_portal:vehicle_request'),
            {
                'requester_name': 'Alex Requester',
                'organization': 'Community Office',
                'contact_number': '09171234567',
                'purpose': 'MEDICAL_TRANSPORT',
                'vehicle_category': 'LAND',
                'requested_for': timezone.make_aware(datetime(2030, 1, 1, 12, 30)),
                'pickup_location': 'Town Hall',
                'destination': 'District Hospital',
                'details': 'Transport for a scheduled medical visit.',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, reverse('dashboard_portal:landing'))
        self.assertContains(response, 'Your vehicle request has been submitted')
        self.assertEqual(VehicleRequest.objects.count(), 1)
        self.assertEqual(VehicleRequest.objects.get().status, 'PENDING')

    def test_public_fleet_view_shows_approved_trip_purpose_and_live_location(self):
        driver = Driver.objects.create(
            name='Jordan Driver',
            phone_number='09170001111',
            license_number='LAND-123',
        )
        vehicle_type = VehicleType.objects.create(name='Public Land Vehicle')
        vehicle = Vehicle.objects.create(
            model_name='Public Rescue Truck',
            plate_number='PUBLIC-001',
            vehicle_type=vehicle_type,
            status='DEPLOYED',
            assigned_driver=driver,
        )
        VehicleRequest.objects.create(
            requester_name='Private Requester',
            contact_number='09179998888',
            purpose='MEDICAL_TRANSPORT',
            vehicle_category='LAND',
            requested_for=timezone.now() + timedelta(hours=1),
            pickup_location='Town Hall',
            destination='District Hospital',
            details='Private request details.',
            assigned_driver=driver,
            assigned_vehicle=vehicle,
            status='APPROVED',
            tracking_token=uuid.uuid4(),
            tracking_expires_at=timezone.now() + timedelta(hours=25),
            current_latitude=9.75,
            current_longitude=118.74,
            location_updated_at=timezone.now(),
        )

        response = self.client.get(reverse('dashboard_portal:homepage'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Medical transport')
        self.assertContains(response, 'Town Hall')
        self.assertContains(response, 'ACTIVE FIELD DEPLOYMENTS')
        self.assertContains(response, 'Destination')
        self.assertContains(response, 'District Hospital')
        self.assertContains(response, 'Public Rescue Truck')
        self.assertContains(response, 'data-deployment-trip=')
        self.assertContains(response, 'View latest location on map')
        self.assertNotContains(response, '09170001111')
        self.assertNotContains(response, '09179998888')
        self.assertNotContains(response, 'Private Requester')


class LandVehicleRequestReviewTests(TestCase):
    def setUp(self):
        group = Group.objects.create(name='Logistics Officers')
        self.user = User.objects.create_user(
            username='land_logistics',
            password='SecurePass123!',
        )
        self.user.groups.add(group)
        self.client.force_login(self.user)
        self.driver = Driver.objects.create(
            name='Jordan Driver',
            phone_number='09170001111',
            license_number='LAND-123',
        )
        self.vehicle_type = VehicleType.objects.create(name='Assigned land fleet')
        self.vehicle = Vehicle.objects.create(
            model_name='Rescue Truck',
            plate_number='ASSIGN-001',
            vehicle_type=self.vehicle_type,
            status='OPERATIONAL',
        )

    def create_request(self, **overrides):
        values = {
            'requester_name': 'Alex Requester',
            'contact_number': '09171234567',
            'purpose': 'OFFICIAL_BUSINESS',
            'vehicle_category': 'LAND',
            'requested_for': timezone.make_aware(datetime(2030, 1, 1, 12, 30)),
            'pickup_location': 'Town Hall',
            'destination': 'Provincial Office',
            'details': 'Official transport request.',
        }
        values.update(overrides)
        return VehicleRequest.objects.create(**values)

    def test_notification_drawer_shows_pending_land_requests_only(self):
        self.create_request()
        self.create_request(
            requester_name='Sea Requester',
            vehicle_category='SEA',
        )

        response = self.client.get(reverse('dashboard_portal:logistics_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Land Vehicle Requests')
        self.assertContains(response, 'Vehicle Requests')
        self.assertContains(response, 'id="operationsDrawer"')
        self.assertContains(response, 'aria-label="Open Logistics menu"')
        self.assertContains(response, 'onboard-trigger-btn')
        self.assertContains(response, 'data-menu-action="print"')
        self.assertContains(response, 'Onboard New Fleet Asset')
        self.assertContains(response, 'Print')
        self.assertContains(response, 'addVehicleModal')
        self.assertContains(response, 'generateReportModal')
        self.assertContains(response, 'deploymentConfirmModal')
        self.assertContains(response, 'name="deployment_purpose"')
        self.assertContains(response, 'name="deployment_destination"')
        self.assertContains(response, 'Assign driver / operator')
        self.assertContains(response, 'name="format"')
        self.assertContains(response, 'Excel (.xlsx)')
        self.assertContains(response, 'PDF (.pdf)')
        self.assertContains(response, 'Land fleet assets')
        self.assertContains(response, 'Land vehicle requests')
        self.assertContains(response, 'Available driver')
        self.assertContains(response, 'Jordan Driver')
        self.assertContains(response, 'Available vehicle')
        self.assertContains(response, 'Rescue Truck')
        self.assertContains(response, 'Alex Requester')
        self.assertNotContains(response, 'Sea Requester')

    def test_logistics_manifest_shows_destination_and_live_vehicle_location(self):
        vehicle_request = self.create_request(
            status='APPROVED',
            assigned_driver=self.driver,
            assigned_vehicle=self.vehicle,
            tracking_token=uuid.uuid4(),
            tracking_expires_at=timezone.now() + timedelta(hours=5),
            current_latitude=9.75,
            current_longitude=118.74,
            location_updated_at=timezone.now(),
        )
        self.vehicle.status = 'DEPLOYED'
        self.vehicle.assigned_driver = self.driver
        self.vehicle.save(update_fields=['status', 'assigned_driver'])

        response = self.client.get(reverse('dashboard_portal:logistics_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Personnel Deployment & Asset Tracking Manifest')
        self.assertContains(response, 'Deployment purpose')
        self.assertContains(response, 'Official business')
        self.assertContains(response, 'Destination')
        self.assertContains(response, vehicle_request.destination)
        self.assertContains(response, 'data-manifest-location="{}"'.format(self.vehicle.id))
        self.assertContains(response, 'https://www.google.com/maps?q=9.75,118.74')
        self.assertContains(response, 'refreshManifestLocations')

    def test_manual_deployment_requires_and_saves_purpose_destination_and_driver(self):
        response = self.client.post(
            reverse('dashboard_portal:logistics_dashboard'),
            {
                'action': 'deploy_vehicle',
                'vehicle_id': self.vehicle.id,
                'deployment_purpose': 'RESCUE_OPERATION',
                'deployment_destination': 'North District',
                'driver_id': self.driver.id,
            },
        )

        self.assertRedirects(response, reverse('dashboard_portal:logistics_dashboard'))
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status, 'DEPLOYED')
        self.assertEqual(self.vehicle.assigned_driver, self.driver)
        self.assertEqual(self.vehicle.deployment_purpose, 'RESCUE_OPERATION')
        self.assertEqual(self.vehicle.deployment_destination, 'North District')

        public_response = self.client.get(reverse('dashboard_portal:homepage'))
        self.assertContains(public_response, 'Rescue operation')
        self.assertContains(public_response, 'North District')

    def test_manual_deployment_rejects_unavailable_or_invalid_driver(self):
        response = self.client.post(
            reverse('dashboard_portal:logistics_dashboard'),
            {
                'action': 'deploy_vehicle',
                'vehicle_id': self.vehicle.id,
                'deployment_purpose': 'RESCUE_OPERATION',
                'deployment_destination': 'North District',
                'driver_id': '99999',
            },
            follow=True,
        )

        self.assertContains(response, 'Select a currently available driver qualified')
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status, 'OPERATIONAL')
        self.assertEqual(self.vehicle.deployment_purpose, '')

    def test_returning_vehicle_clears_deployment_details(self):
        self.vehicle.status = 'DEPLOYED'
        self.vehicle.assigned_driver = self.driver
        self.vehicle.deployment_purpose = 'RESCUE_OPERATION'
        self.vehicle.deployment_destination = 'North District'
        self.vehicle.save()

        response = self.client.post(
            reverse('dashboard_portal:logistics_dashboard'),
            {
                'action': 'return_vehicle',
                'vehicle_id': self.vehicle.id,
            },
        )

        self.assertRedirects(response, reverse('dashboard_portal:logistics_dashboard'))
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status, 'OPERATIONAL')
        self.assertEqual(self.vehicle.deployment_purpose, '')
        self.assertEqual(self.vehicle.deployment_destination, '')

    def test_drawer_includes_previous_land_requests_and_decisions(self):
        self.create_request(
            requester_name='Approved Requester',
            status='APPROVED',
            staff_notes='Vehicle assigned.',
        )
        self.create_request(
            requester_name='Denied Requester',
            status='DECLINED',
            staff_notes='No vehicle available.',
        )
        self.create_request(
            requester_name='Sea Requester',
            vehicle_category='SEA',
            status='APPROVED',
        )

        response = self.client.get(reverse('dashboard_portal:logistics_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Previous')
        self.assertContains(response, 'Approved Requester')
        self.assertContains(response, 'Denied Requester')
        self.assertContains(response, 'Vehicle assigned.')
        self.assertContains(response, 'No vehicle available.')
        self.assertNotContains(response, 'Sea Requester')

    def test_land_request_can_be_approved_with_staff_notes(self):
        vehicle_request = self.create_request()

        response = self.client.post(
            reverse('dashboard_portal:logistics_dashboard'),
            {
                'action': 'approve_vehicle_request',
                'request_id': vehicle_request.id,
                'driver_id': self.driver.id,
                'assigned_vehicle_id': self.vehicle.id,
                'staff_notes': 'Vehicle assigned for the trip.',
            },
        )

        vehicle_request.refresh_from_db()
        self.assertRedirects(response, reverse('dashboard_portal:logistics_dashboard'))
        self.assertEqual(vehicle_request.status, 'APPROVED')
        self.assertEqual(vehicle_request.staff_notes, 'Vehicle assigned for the trip.')
        self.assertEqual(vehicle_request.assigned_driver, self.driver)
        self.assertEqual(vehicle_request.assigned_vehicle, self.vehicle)
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status, 'DEPLOYED')
        self.assertEqual(self.vehicle.assigned_driver, self.driver)
        self.assertEqual(self.vehicle.deployment_purpose, vehicle_request.purpose)
        self.assertEqual(self.vehicle.deployment_destination, vehicle_request.destination)
        self.assertIsNotNone(vehicle_request.tracking_token)
        self.assertEqual(
            vehicle_request.tracking_expires_at,
            vehicle_request.requested_for + timedelta(hours=24),
        )
        response = self.client.get(reverse('dashboard_portal:logistics_dashboard'))
        self.assertContains(response, 'Open private driver sharing link')
        self.assertContains(response, 'Send link to driver')
        self.assertContains(
            response,
            reverse(
                'dashboard_portal:driver_location_sharing',
                args=[vehicle_request.tracking_token],
            ),
        )

    def test_land_request_can_be_rejected(self):
        vehicle_request = self.create_request()

        response = self.client.post(
            reverse('dashboard_portal:logistics_dashboard'),
            {
                'action': 'reject_vehicle_request',
                'request_id': vehicle_request.id,
                'staff_notes': 'No vehicle is available.',
            },
        )

        vehicle_request.refresh_from_db()
        self.assertRedirects(response, reverse('dashboard_portal:logistics_dashboard'))
        self.assertEqual(vehicle_request.status, 'DECLINED')
        self.assertEqual(vehicle_request.staff_notes, 'No vehicle is available.')
        self.assertIsNone(vehicle_request.assigned_driver)

    def test_land_request_cannot_be_approved_without_available_driver(self):
        vehicle_request = self.create_request()

        response = self.client.post(
            reverse('dashboard_portal:logistics_dashboard'),
            {
                'action': 'approve_vehicle_request',
                'request_id': vehicle_request.id,
                'driver_id': '99999',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Select a currently available land driver')
        vehicle_request.refresh_from_db()
        self.assertEqual(vehicle_request.status, 'PENDING')

    def test_land_request_with_expired_tracking_window_cannot_be_approved(self):
        vehicle_request = self.create_request(
            requested_for=timezone.now() - timedelta(hours=25),
        )

        response = self.client.post(
            reverse('dashboard_portal:logistics_dashboard'),
            {
                'action': 'approve_vehicle_request',
                'request_id': vehicle_request.id,
                'driver_id': self.driver.id,
                'assigned_vehicle_id': self.vehicle.id,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'location-sharing window has expired')
        vehicle_request.refresh_from_db()
        self.assertEqual(vehicle_request.status, 'PENDING')

    def test_land_request_cannot_be_approved_without_available_vehicle(self):
        vehicle_request = self.create_request()
        self.vehicle.status = 'DEPLOYED'
        self.vehicle.save(update_fields=['status'])

        response = self.client.post(
            reverse('dashboard_portal:logistics_dashboard'),
            {
                'action': 'approve_vehicle_request',
                'request_id': vehicle_request.id,
                'driver_id': self.driver.id,
                'assigned_vehicle_id': self.vehicle.id,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Select a currently available land vehicle')
        vehicle_request.refresh_from_db()
        self.assertEqual(vehicle_request.status, 'PENDING')
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status, 'DEPLOYED')

    def test_approved_trip_keeps_driver_unavailable_after_tracking_expiry(self):
        self.create_request(
            status='APPROVED',
            assigned_driver=self.driver,
            tracking_expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.create_request(requester_name='Second Requester')

        response = self.client.get(reverse('dashboard_portal:logistics_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.driver, response.context['available_land_request_drivers'])

    def test_driver_can_share_location_using_private_tracking_link(self):
        vehicle_request = self.create_request(
            status='APPROVED',
            assigned_driver=self.driver,
            tracking_token=uuid.uuid4(),
            tracking_expires_at=timezone.now() + timedelta(hours=5),
        )

        response = self.client.post(
            reverse(
                'dashboard_portal:driver_location_sharing',
                args=[vehicle_request.tracking_token],
            ),
            {'latitude': '9.75', 'longitude': '118.74'},
        )

        self.assertEqual(response.status_code, 200)
        vehicle_request.refresh_from_db()
        self.assertEqual(vehicle_request.current_latitude, 9.75)
        self.assertEqual(vehicle_request.current_longitude, 118.74)
        self.assertIsNotNone(vehicle_request.location_updated_at)

    def test_driver_tracking_page_is_mobile_friendly_and_offers_live_sharing(self):
        vehicle_request = self.create_request(
            status='APPROVED',
            assigned_driver=self.driver,
            tracking_token=uuid.uuid4(),
            tracking_expires_at=timezone.now() + timedelta(hours=5),
        )

        response = self.client.get(
            reverse(
                'dashboard_portal:driver_location_sharing',
                args=[vehicle_request.tracking_token],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertContains(response, 'name="viewport"')
        self.assertContains(response, 'Share your live location')
        self.assertContains(response, 'Provincial Office')
        self.assertContains(response, 'Retry live sharing')
        self.assertContains(response, 'sharing starts automatically')
        self.assertContains(response, 'Pause sharing')
        self.assertContains(response, 'navigator.geolocation.watchPosition')
        self.assertContains(response, 'window.isSecureContext === false')
        self.assertContains(response, 'Keeping location watch active and retrying')
        self.assertContains(response, 'Retrying automatically')
        self.assertContains(response, 'startSharing();')
        self.assertContains(response, 'Report a damaged or destroyed unit')
        self.assertContains(response, 'name="condition"')
        self.assertContains(response, 'name="description"')

    def test_driver_dashboard_detects_assigned_active_trip(self):
        vehicle_request = self.create_request(
            status='APPROVED',
            assigned_driver=self.driver,
            assigned_vehicle=self.vehicle,
            tracking_token=uuid.uuid4(),
            tracking_expires_at=timezone.now() + timedelta(hours=5),
        )
        driver_user = User.objects.create_user(
            username='active_trip_dashboard_driver',
            password='DriverSecurePass!2026',
        )
        self.driver.user = driver_user
        self.driver.save(update_fields=['user'])
        self.client.force_login(driver_user)

        dashboard = self.client.get(reverse('dashboard_portal:driver_dashboard'))
        self.assertContains(dashboard, 'driver-dashboard')
        self.assertContains(dashboard, 'Share your live location')
        self.assertContains(dashboard, 'navigator.geolocation.watchPosition')
        self.assertContains(dashboard, 'data-update-url="{}"'.format(
            reverse(
                'dashboard_portal:driver_location_sharing',
                args=[vehicle_request.tracking_token],
            ),
        ))

        active_trip = self.client.get(reverse('dashboard_portal:driver_active_trip'))
        self.assertEqual(active_trip.status_code, 200)
        self.assertEqual(
            active_trip.json()['tracking_url'],
            reverse(
                'dashboard_portal:driver_location_sharing',
                args=[vehicle_request.tracking_token],
            ),
        )

    def test_driver_can_report_damaged_unit_and_logistics_can_review_it(self):
        vehicle_request = self.create_request(
            status='APPROVED',
            assigned_driver=self.driver,
            assigned_vehicle=self.vehicle,
            tracking_token=uuid.uuid4(),
            tracking_expires_at=timezone.now() + timedelta(hours=5),
        )
        tracking_url = reverse(
            'dashboard_portal:driver_location_sharing',
            args=[vehicle_request.tracking_token],
        )

        response = self.client.post(
            tracking_url,
            {
                'action': 'report_unit_condition',
                'condition': 'DAMAGED',
                'description': 'The front passenger-side tire is damaged.',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'unit condition report was sent to Logistics')
        report = UnitConditionReport.objects.get()
        self.assertEqual(report.vehicle, self.vehicle)
        self.assertEqual(report.driver, self.driver)
        self.assertEqual(report.vehicle_request, vehicle_request)
        self.assertEqual(report.condition, 'DAMAGED')
        self.assertEqual(report.status, 'OPEN')
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status, 'OPERATIONAL')

        dashboard_response = self.client.get(reverse('dashboard_portal:logistics_dashboard'))
        self.assertContains(dashboard_response, 'Driver Unit Condition Reports')
        self.assertContains(dashboard_response, 'The front passenger-side tire is damaged.')

        response = self.client.post(
            reverse('dashboard_portal:logistics_dashboard'),
            {
                'action': 'review_unit_condition_report',
                'report_id': report.id,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        report.refresh_from_db()
        self.assertEqual(report.status, 'REVIEWED')
        self.assertNotContains(response, 'Driver Unit Condition Reports')

    def test_driver_unit_report_requires_valid_condition_and_description(self):
        vehicle_request = self.create_request(
            status='APPROVED',
            assigned_driver=self.driver,
            assigned_vehicle=self.vehicle,
            tracking_token=uuid.uuid4(),
            tracking_expires_at=timezone.now() + timedelta(hours=5),
        )

        response = self.client.post(
            reverse(
                'dashboard_portal:driver_location_sharing',
                args=[vehicle_request.tracking_token],
            ),
            {
                'action': 'report_unit_condition',
                'condition': 'BROKEN',
                'description': '',
            },
            follow=True,
        )

        self.assertContains(response, 'Select whether the unit is damaged or destroyed.')
        self.assertEqual(UnitConditionReport.objects.count(), 0)

    def test_expired_driver_tracking_link_cannot_update_location(self):
        vehicle_request = self.create_request(
            status='APPROVED',
            assigned_driver=self.driver,
            tracking_token=uuid.uuid4(),
            tracking_expires_at=timezone.now() - timedelta(minutes=1),
        )

        response = self.client.post(
            reverse(
                'dashboard_portal:driver_location_sharing',
                args=[vehicle_request.tracking_token],
            ),
            {'latitude': '9.75', 'longitude': '118.74'},
        )

        self.assertEqual(response.status_code, 410)
        vehicle_request.refresh_from_db()
        self.assertIsNone(vehicle_request.current_latitude)

    def test_driver_tracking_rejects_invalid_coordinates(self):
        vehicle_request = self.create_request(
            status='APPROVED',
            assigned_driver=self.driver,
            tracking_token=uuid.uuid4(),
            tracking_expires_at=timezone.now() + timedelta(hours=5),
        )

        response = self.client.post(
            reverse(
                'dashboard_portal:driver_location_sharing',
                args=[vehicle_request.tracking_token],
            ),
            {'latitude': '120', 'longitude': '500'},
        )

        self.assertEqual(response.status_code, 400)
        vehicle_request.refresh_from_db()
        self.assertIsNone(vehicle_request.current_latitude)

    def test_public_trip_location_exposes_purpose_and_coordinates_only(self):
        vehicle_request = self.create_request(
            status='APPROVED',
            assigned_driver=self.driver,
            assigned_vehicle=self.vehicle,
            tracking_token=uuid.uuid4(),
            tracking_expires_at=timezone.now() + timedelta(hours=5),
            current_latitude=9.75,
            current_longitude=118.74,
            location_updated_at=timezone.now(),
        )
        self.vehicle.status = 'DEPLOYED'
        self.vehicle.save(update_fields=['status'])

        response = self.client.get(reverse('dashboard_portal:public_trip_locations'))

        self.assertEqual(response.status_code, 200)
        trip = response.json()['trips'][0]
        self.assertEqual(trip['purpose'], 'Official business')
        self.assertEqual(trip['vehicle_id'], self.vehicle.id)
        self.assertEqual(trip['latitude'], 9.75)
        self.assertEqual(trip['longitude'], 118.74)
        self.assertNotIn('driver_phone', trip)
        self.assertNotIn('requester_name', trip)

    def test_ending_trip_revokes_tracking_and_hides_it_from_public_view(self):
        vehicle_request = self.create_request(
            status='APPROVED',
            assigned_driver=self.driver,
            assigned_vehicle=self.vehicle,
            tracking_token=uuid.uuid4(),
            tracking_expires_at=timezone.now() + timedelta(hours=5),
            current_latitude=9.75,
            current_longitude=118.74,
            location_updated_at=timezone.now(),
        )
        self.vehicle.status = 'DEPLOYED'
        self.vehicle.save(update_fields=['status'])

        response = self.client.post(
            reverse('dashboard_portal:logistics_dashboard'),
            {
                'action': 'complete_vehicle_request',
                'request_id': vehicle_request.id,
            },
        )

        vehicle_request.refresh_from_db()
        self.assertRedirects(response, reverse('dashboard_portal:logistics_dashboard'))
        self.assertEqual(vehicle_request.status, 'COMPLETED')
        self.assertIsNone(vehicle_request.tracking_token)
        self.assertIsNone(vehicle_request.current_latitude)
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status, 'OPERATIONAL')
        self.assertEqual(self.vehicle.deployment_purpose, '')
        self.assertEqual(self.vehicle.deployment_destination, '')
        self.assertEqual(
            self.client.get(reverse('dashboard_portal:public_trip_locations')).json()['trips'],
            [],
        )

    def test_land_dispatch_report_downloads_fleet_and_request_csv(self):
        land_type = VehicleType.objects.create(name='Truck')
        marine_type = VehicleType.objects.create(name='Marine')
        Vehicle.objects.create(
            model_name='Rescue Truck',
            plate_number='LAND-001',
            vehicle_type=land_type,
            status='OPERATIONAL',
        )
        Vehicle.objects.create(
            model_name='Archived Truck',
            plate_number='LAND-002',
            vehicle_type=land_type,
            status='ARCHIVED',
        )
        Vehicle.objects.create(
            model_name='Patrol Boat',
            plate_number='SEA-001',
            vehicle_type=marine_type,
            status='OPERATIONAL',
        )
        self.create_request(
            requester_name='Report Requester',
            assigned_driver=self.driver,
            assigned_vehicle=self.vehicle,
        )

        response = self.client.get(
            reverse('dashboard_portal:land_dispatch_report'),
            {'dataset': ['land_fleet', 'vehicle_requests'], 'format': 'csv'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('attachment;', response['Content-Disposition'])
        report = response.content.decode('utf-8')
        self.assertIn('Rescue Truck', report)
        self.assertIn('Report Requester', report)
        self.assertNotIn('Archived Truck', report)
        self.assertNotIn('Patrol Boat', report)

    def test_land_dispatch_report_includes_only_selected_dataset(self):
        land_type = VehicleType.objects.create(name='Truck')
        Vehicle.objects.create(
            model_name='Rescue Truck',
            plate_number='LAND-001',
            vehicle_type=land_type,
            status='OPERATIONAL',
        )
        self.create_request(requester_name='Report Requester')

        response = self.client.get(
            reverse('dashboard_portal:land_dispatch_report'),
            {'dataset': 'land_fleet', 'format': 'csv'},
        )

        self.assertEqual(response.status_code, 200)
        report = response.content.decode('utf-8')
        self.assertIn('Rescue Truck', report)
        self.assertNotIn('Report Requester', report)
        self.assertNotIn('LAND VEHICLE REQUESTS', report)

    def test_land_dispatch_report_requires_a_valid_format(self):
        response = self.client.get(
            reverse('dashboard_portal:land_dispatch_report'),
            {'dataset': 'land_fleet'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            'Select a valid report format.',
            status_code=400,
        )

    def test_land_dispatch_report_requires_at_least_one_dataset(self):
        response = self.client.get(
            reverse('dashboard_portal:land_dispatch_report'),
            {'format': 'csv'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            'Select at least one valid report dataset.',
            status_code=400,
        )

    def test_land_dispatch_report_downloads_pdf(self):
        VehicleType.objects.create(name='Truck')

        response = self.client.get(
            reverse('dashboard_portal:land_dispatch_report'),
            {'dataset': ['land_fleet', 'vehicle_requests'], 'format': 'pdf'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('.pdf', response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_land_dispatch_report_downloads_excel_workbook(self):
        land_type = VehicleType.objects.create(name='Truck')
        Vehicle.objects.create(
            model_name='Rescue Truck',
            plate_number='LAND-001',
            vehicle_type=land_type,
            status='OPERATIONAL',
        )

        response = self.client.get(
            reverse('dashboard_portal:land_dispatch_report'),
            {'dataset': 'land_fleet', 'format': 'excel'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        workbook = load_workbook(BytesIO(response.content), read_only=True)
        self.assertEqual(workbook.sheetnames, ['Land Fleet'])
        self.assertEqual(workbook['Land Fleet']['B2'].value, 'Rescue Truck')

    def test_land_dispatch_report_rejects_unknown_format(self):
        response = self.client.get(
            reverse('dashboard_portal:land_dispatch_report'),
            {'dataset': 'land_fleet', 'format': 'ods'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            'Select a valid report format.',
            status_code=400,
        )

    def test_land_dispatch_report_requires_logistics_access(self):
        user = User.objects.create_user(username='unauthorized_user', password='SecurePass123!')
        self.client.force_login(user)
        response = self.client.get(reverse('dashboard_portal:land_dispatch_report'))

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('dashboard_portal:homepage'))


class MaintenanceLogTests(TestCase):
    def test_land_mechanic_can_log_service_without_changing_vehicle_status(self):
        mechanic = User.objects.create_user(
            username='fleet_mechanic',
            password='MechanicSecurePass!2026',
        )
        vehicle_type = VehicleType.objects.create(name='Maintenance Test Truck')
        vehicle = Vehicle.objects.create(
            model_name='Oil Service Truck',
            plate_number='OIL-LOG-01',
            vehicle_type=vehicle_type,
            status='OPERATIONAL',
        )
        self.client.force_login(mechanic)

        response = self.client.post(
            reverse('dashboard_portal:repairman_dashboard'),
            {
                'vehicle_id': vehicle.id,
                'action_type': 'ADD_MAINTENANCE_LOG',
                'service_item': 'Oil change',
                'details': 'Engine oil and filter replaced.',
            },
        )

        self.assertRedirects(response, reverse('dashboard_portal:repairman_dashboard'))
        self.assertEqual(
            MaintenanceLog.objects.get().service_item,
            'Oil change',
        )
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, 'OPERATIONAL')

    def test_land_mechanic_must_record_problem_when_sending_unit_to_maintenance(self):
        mechanic = User.objects.create_user(
            username='land_mechanic_problem',
            password='MechanicSecurePass!2026',
        )
        vehicle_type = VehicleType.objects.create(name='Maintenance Problem Truck')
        vehicle = Vehicle.objects.create(
            model_name='Problem Test Truck',
            plate_number='PROBLEM-01',
            vehicle_type=vehicle_type,
            status='OPERATIONAL',
        )
        self.client.force_login(mechanic)

        response = self.client.post(
            reverse('dashboard_portal:repairman_dashboard'),
            {
                'vehicle_id': vehicle.id,
                'action_type': 'SET_STATUS',
                'status': 'MAINTENANCE',
            },
            follow=True,
        )

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, 'OPERATIONAL')
        self.assertContains(response, 'Describe the problem before sending the vehicle to maintenance')

        response = self.client.post(
            reverse('dashboard_portal:repairman_dashboard'),
            {
                'vehicle_id': vehicle.id,
                'action_type': 'SET_STATUS',
                'status': 'MAINTENANCE',
                'maintenance_problem': 'Engine will not start; battery voltage is low.',
            },
            follow=True,
        )

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, 'MAINTENANCE')
        self.assertEqual(
            vehicle.maintenance_problem,
            'Engine will not start; battery voltage is low.',
        )
        self.assertContains(response, 'Engine will not start; battery voltage is low.')

    def test_land_mechanic_must_complete_checklist_before_marking_operational(self):
        mechanic = User.objects.create_user(
            username='land_mechanic_checklist',
            password='MechanicSecurePass!2026',
        )
        vehicle_type = VehicleType.objects.create(name='Checklist Truck')
        vehicle = Vehicle.objects.create(
            model_name='Checklist Test Truck',
            plate_number='CHECK-LAND-01',
            vehicle_type=vehicle_type,
            status='MAINTENANCE',
            maintenance_problem='Brake warning light is on.',
        )
        self.client.force_login(mechanic)
        url = reverse('dashboard_portal:repairman_dashboard')

        response = self.client.post(
            url,
            {
                'vehicle_id': vehicle.id,
                'action_type': 'SET_STATUS',
                'status': 'OPERATIONAL',
                'maintenance_checklist': ['repairs_complete'],
            },
            follow=True,
        )

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, 'MAINTENANCE')
        self.assertContains(response, 'Confirm every return-to-service checklist item')

        checklist = [
            'repairs_complete',
            'safety_systems_checked',
            'fluids_battery_tires_checked',
            'test_run_passed',
            'no_unresolved_issues',
        ]
        response = self.client.post(
            url,
            {
                'vehicle_id': vehicle.id,
                'action_type': 'SET_STATUS',
                'status': 'OPERATIONAL',
                'maintenance_checklist': checklist,
            },
            follow=True,
        )

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, 'OPERATIONAL')
        self.assertEqual(vehicle.maintenance_problem, '')
        self.assertContains(response, 'marked as Operational')

    def test_land_mechanic_dashboard_has_separate_maintenance_tab_without_toggle(self):
        mechanic = User.objects.create_user(
            username='fleet_mechanic_tabs',
            password='MechanicSecurePass!2026',
        )
        self.client.force_login(mechanic)

        response = self.client.get(reverse('dashboard_portal:repairman_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['fleet_status'], 'MAINTENANCE_DISPOSAL')
        self.assertEqual(
            response.context['fleet_status_tabs'][0][0],
            'MAINTENANCE_DISPOSAL',
        )
        self.assertContains(response, 'href="?status=MAINTENANCE_DISPOSAL"')
        self.assertContains(response, 'href="?status=OPERATIONAL"')
        self.assertNotContains(response, 'STATUS_TOGGLE')
        self.assertNotContains(response, 'type="checkbox"')

    def test_land_mechanic_dashboard_prioritizes_maintenance_and_disposal_by_default(self):
        mechanic = User.objects.create_user(
            username='fleet_mechanic_default_priority',
            password='MechanicSecurePass!2026',
        )
        land_type = VehicleType.objects.create(name='Default Priority Truck')
        maintenance_vehicle = Vehicle.objects.create(
            model_name='Priority Maintenance Unit',
            plate_number='LAND-PRI-M',
            vehicle_type=land_type,
            status='MAINTENANCE',
        )
        disposal_vehicle = Vehicle.objects.create(
            model_name='Priority Disposal Unit',
            plate_number='LAND-PRI-D',
            vehicle_type=land_type,
            status='PENDING_DISPOSAL',
        )
        self.client.force_login(mechanic)

        response = self.client.get(reverse('dashboard_portal:repairman_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.context['vehicles'].values_list('id', flat=True)),
            {maintenance_vehicle.id, disposal_vehicle.id},
        )
        self.assertContains(response, 'Priority Maintenance Unit')
        self.assertContains(response, 'Priority Disposal Unit')

    def test_land_mechanic_maintenance_tab_includes_pending_disposal_assets(self):
        mechanic = User.objects.create_user(
            username='fleet_mechanic_filter',
            password='MechanicSecurePass!2026',
        )
        land_type = VehicleType.objects.create(name='Land Tab Test')
        maintenance_vehicle = Vehicle.objects.create(
            model_name='Maintenance Tab Unit',
            plate_number='LAND-TAB-M',
            vehicle_type=land_type,
            status='MAINTENANCE',
        )
        disposal_vehicle = Vehicle.objects.create(
            model_name='Pending Disposal Tab Unit',
            plate_number='LAND-TAB-D',
            vehicle_type=land_type,
            status='PENDING_DISPOSAL',
        )
        Vehicle.objects.create(
            model_name='Operational Tab Unit',
            plate_number='LAND-TAB-O',
            vehicle_type=land_type,
            status='OPERATIONAL',
        )
        self.client.force_login(mechanic)

        response = self.client.get(
            reverse('dashboard_portal:repairman_dashboard'),
            {'status': 'MAINTENANCE_DISPOSAL'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['fleet_status'], 'MAINTENANCE_DISPOSAL')
        self.assertEqual(
            set(response.context['vehicles'].values_list('id', flat=True)),
            {maintenance_vehicle.id, disposal_vehicle.id},
        )
        self.assertContains(response, 'Maintenance Tab Unit')
        self.assertContains(response, '<th class="py-2">Problem</th>', html=True)
        self.assertContains(response, 'Pending Disposal Tab Unit')
        self.assertNotContains(response, 'Operational Tab Unit')

    def test_maritime_mechanic_can_log_seacraft_service(self):
        mechanic = User.objects.create_user(
            username='maritime_mechanic',
            password='MechanicSecurePass!2026',
        )
        marine_type = VehicleType.objects.create(name='MARINE')
        craft = Vehicle.objects.create(
            model_name='Rescue Boat',
            plate_number='SEA-LOG-01',
            vehicle_type=marine_type,
            status='OPERATIONAL',
        )
        self.client.force_login(mechanic)

        response = self.client.post(
            reverse('dashboard_portal:seacraft_dashboard'),
            {
                'vehicle_id': craft.id,
                'action_type': 'ADD_MAINTENANCE_LOG',
                'service_item': 'Battery replacement',
                'details': 'Replaced starting battery.',
            },
        )

        self.assertRedirects(response, reverse('dashboard_portal:seacraft_dashboard'))
        self.assertEqual(MaintenanceLog.objects.get().vehicle, craft)
        craft.refresh_from_db()
        self.assertEqual(craft.status, 'OPERATIONAL')

    def test_seacraft_workbench_records_and_displays_maintenance_problem(self):
        mechanic = User.objects.create_user(
            username='maritime_mechanic_problem',
            password='MechanicSecurePass!2026',
        )
        marine_type = VehicleType.objects.create(name='MARINE')
        craft = Vehicle.objects.create(
            model_name='Problem Test Seacraft',
            plate_number='SEA-PROBLEM-01',
            vehicle_type=marine_type,
            status='OPERATIONAL',
        )
        self.client.force_login(mechanic)

        response = self.client.post(
            reverse('dashboard_portal:seacraft_dashboard'),
            {
                'vehicle_id': craft.id,
                'action_type': 'SET_STATUS',
                'status': 'MAINTENANCE',
                'maintenance_problem': 'Port engine overheats after 20 minutes.',
            },
            follow=True,
        )

        craft.refresh_from_db()
        self.assertEqual(craft.status, 'MAINTENANCE')
        self.assertEqual(craft.maintenance_problem, 'Port engine overheats after 20 minutes.')
        self.assertContains(response, 'Port engine overheats after 20 minutes.')

    def test_seacraft_mechanic_must_complete_checklist_before_marking_operational(self):
        mechanic = User.objects.create_user(
            username='maritime_mechanic_checklist',
            password='MechanicSecurePass!2026',
        )
        marine_type = VehicleType.objects.create(name='MARINE')
        craft = Vehicle.objects.create(
            model_name='Checklist Test Boat',
            plate_number='CHECK-SEA-01',
            vehicle_type=marine_type,
            status='MAINTENANCE',
            maintenance_problem='Port engine overheats.',
        )
        self.client.force_login(mechanic)
        url = reverse('dashboard_portal:seacraft_dashboard')

        response = self.client.post(
            url,
            {
                'vehicle_id': craft.id,
                'action_type': 'SET_STATUS',
                'status': 'OPERATIONAL',
            },
            follow=True,
        )

        craft.refresh_from_db()
        self.assertEqual(craft.status, 'MAINTENANCE')
        self.assertContains(response, 'Confirm every return-to-service checklist item')

    def test_seacraft_dispatch_requires_checklist_to_complete_maintenance(self):
        dispatcher = User.objects.create_user(
            username='maritime_dispatch_checklist',
            password='DispatcherSecurePass!2026',
        )
        marine_type = VehicleType.objects.create(name='MARINE')
        craft = Vehicle.objects.create(
            model_name='Dispatch Checklist Boat',
            plate_number='CHECK-SEA-02',
            vehicle_type=marine_type,
            status='MAINTENANCE',
            maintenance_problem='Battery does not hold charge.',
        )
        self.client.force_login(dispatcher)
        url = reverse('dashboard_portal:seacraft_dispatch')

        response = self.client.post(
            url,
            {
                'vehicle_id': craft.id,
                'action': 'complete_maintenance',
                'maintenance_checklist': ['repairs_complete'],
            },
            follow=True,
        )

        craft.refresh_from_db()
        self.assertEqual(craft.status, 'MAINTENANCE')
        self.assertContains(response, 'Confirm every return-to-service checklist item')

    def test_seacraft_workbench_renders_separate_maintenance_tab(self):
        mechanic = User.objects.create_user(
            username='maritime_mechanic_tabs',
            password='MechanicSecurePass!2026',
        )
        marine_type = VehicleType.objects.create(name='MARINE')
        Vehicle.objects.create(
            model_name='Tab Test Rescue Boat',
            plate_number='SEA-TAB-01',
            vehicle_type=marine_type,
            status='MAINTENANCE',
        )
        self.client.force_login(mechanic)

        response = self.client.get(reverse('dashboard_portal:seacraft_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-fleet-filter="MAINTENANCE"')
        self.assertContains(response, 'Tab Test Rescue Boat')
        self.assertContains(response, '<th class="px-3 py-2">Problem</th>', html=True)
        self.assertNotContains(response, 'marine-status-toggle')

    def test_seacraft_dispatch_has_dedicated_maintenance_tab(self):
        dispatcher = User.objects.create_user(
            username='maritime_dispatch_user',
            password='DispatcherSecurePass!2026',
        )
        marine_type = VehicleType.objects.create(name='MARINE')
        craft = Vehicle.objects.create(
            model_name='Dispatch Maintenance Boat',
            plate_number='SEA-DISPATCH-M',
            vehicle_type=marine_type,
            status='MAINTENANCE',
        )
        self.client.force_login(dispatcher)

        response = self.client.get(reverse('dashboard_portal:seacraft_dispatch'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Maintenance</button>')
        self.assertContains(response, 'Dispatch Maintenance Boat')
        self.assertContains(response, 'Mark operational')
