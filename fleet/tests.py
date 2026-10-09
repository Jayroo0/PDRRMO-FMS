from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from .models import Driver, Vehicle, VehicleType


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


class DispatchDashboardAlignmentTests(TestCase):
    def setUp(self):
        self.marine_type = VehicleType.objects.create(name='MARINE')
        self.maritime_type = VehicleType.objects.create(name='MARITIME')
        self.land_type = VehicleType.objects.create(name='LAND')
        self.seacraft_user = User.objects.create_user(
            username='maritime_dispatcher',
            password='SecurePass123!',
        )
        logistics_group = Group.objects.create(name='Logistics Officers')
        self.logistics_user = User.objects.create_user(
            username='fleet_logistics',
            password='SecurePass123!',
        )
        self.logistics_user.groups.add(logistics_group)
        self.operator = Driver.objects.create(
            name='Qualified Maritime Operator',
            license_number='MAR-001',
        )

    def create_vehicle(self, *, model_name, plate_number, vehicle_type, **kwargs):
        return Vehicle.objects.create(
            model_name=model_name,
            plate_number=plate_number,
            vehicle_type=vehicle_type,
            **kwargs,
        )

    def test_maritime_asset_classification_matches_across_dashboards(self):
        marine_craft = self.create_vehicle(
            model_name='Marine Name Craft',
            plate_number='SEA-MARINE-01',
            vehicle_type=self.marine_type,
        )
        maritime_craft = self.create_vehicle(
            model_name='Maritime Name Craft',
            plate_number='SEA-MARITIME-01',
            vehicle_type=self.maritime_type,
        )
        land_vehicle = self.create_vehicle(
            model_name='Land Name Vehicle',
            plate_number='LAND-01',
            vehicle_type=self.land_type,
        )

        self.client.force_login(self.logistics_user)
        logistics_response = self.client.get(reverse('dashboard_portal:logistics_dashboard'))
        self.assertEqual(logistics_response.status_code, 200)
        self.assertEqual(
            {craft.id for craft in logistics_response.context['sea_crafts']},
            {marine_craft.id, maritime_craft.id},
        )
        self.assertEqual(
            {vehicle.id for vehicle in logistics_response.context['land_vehicles']},
            {land_vehicle.id},
        )

        self.client.force_login(self.seacraft_user)
        dispatch_response = self.client.get(reverse('dashboard_portal:seacraft_dispatch'))
        self.assertEqual(dispatch_response.status_code, 200)
        for craft in (marine_craft, maritime_craft):
            self.assertContains(dispatch_response, craft.model_name)
        self.assertNotContains(dispatch_response, land_vehicle.model_name)

    def test_dispatch_deployment_details_are_visible_in_logistics_dashboard(self):
        craft = self.create_vehicle(
            model_name='Shared Dispatch Craft',
            plate_number='SEA-SHARED-01',
            vehicle_type=self.maritime_type,
        )
        self.client.force_login(self.seacraft_user)

        response = self.client.post(
            reverse('dashboard_portal:seacraft_dispatch'),
            {
                'action': 'deploy_vehicle',
                'vehicle_id': craft.id,
                'driver_id': self.operator.id,
                'deployment_location': 'Honda Bay',
                'deployment_purpose': 'Emergency Search & Rescue',
                'deployment_time': '2030-01-02T10:30',
            },
        )

        self.assertRedirects(response, reverse('dashboard_portal:seacraft_dispatch'))
        craft.refresh_from_db()
        self.assertEqual(craft.status, 'DEPLOYED')
        self.assertEqual(craft.assigned_driver, self.operator)
        self.assertEqual(craft.deployment_location, 'Honda Bay')
        self.assertEqual(craft.deployment_purpose, 'Emergency Search & Rescue')
        self.assertIsNotNone(craft.deployment_time)

        self.client.force_login(self.logistics_user)
        dashboard = self.client.get(reverse('dashboard_portal:logistics_dashboard'))
        self.assertContains(dashboard, 'Shared Dispatch Craft')
        self.assertContains(dashboard, 'Honda Bay')
        self.assertContains(dashboard, 'Emergency Search &amp; Rescue')
        self.assertContains(dashboard, 'Qualified Maritime Operator')

    def test_logistics_deployment_details_are_visible_in_seacraft_dispatch(self):
        craft = self.create_vehicle(
            model_name='Logistics Deployed Craft',
            plate_number='SEA-LOGISTICS-01',
            vehicle_type=self.marine_type,
        )
        self.client.force_login(self.logistics_user)

        response = self.client.post(
            reverse('dashboard_portal:logistics_dashboard'),
            {
                'action': 'deploy_vehicle',
                'vehicle_id': craft.id,
                'driver_id': self.operator.id,
                'deployment_location': 'Coron Bay',
                'deployment_purpose': 'Coastal & Sea Patrol / Reconnaissance',
                'deployment_time': '2030-01-03T08:15',
            },
        )

        self.assertRedirects(response, reverse('dashboard_portal:logistics_dashboard'))
        craft.refresh_from_db()
        self.assertEqual(craft.status, 'DEPLOYED')
        self.assertEqual(craft.assigned_driver, self.operator)
        self.assertEqual(craft.deployment_location, 'Coron Bay')
        self.assertEqual(craft.deployment_purpose, 'Coastal & Sea Patrol / Reconnaissance')
        self.assertIsNotNone(craft.deployment_time)

        self.client.force_login(self.seacraft_user)
        dispatch_dashboard = self.client.get(reverse('dashboard_portal:seacraft_dispatch'))
        self.assertContains(dispatch_dashboard, 'Logistics Deployed Craft')
        self.assertContains(dispatch_dashboard, 'Coron Bay')
        self.assertContains(dispatch_dashboard, 'Coastal &amp; Sea Patrol / Reconnaissance')

    def test_dispatch_rejects_nonoperational_craft_and_unqualified_operator(self):
        craft = self.create_vehicle(
            model_name='Blocked Dispatch Craft',
            plate_number='SEA-BLOCKED-01',
            vehicle_type=self.marine_type,
            status='MAINTENANCE',
        )
        land_operator = Driver.objects.create(
            name='Land Driver',
            license_number='LAND-001',
        )
        self.client.force_login(self.seacraft_user)

        response = self.client.post(
            reverse('dashboard_portal:seacraft_dispatch'),
            {
                'action': 'deploy_vehicle',
                'vehicle_id': craft.id,
                'driver_id': self.operator.id,
                'deployment_location': 'Honda Bay',
                'deployment_purpose': 'Emergency Search & Rescue',
                'deployment_time': '2030-01-02T10:30',
            },
            follow=True,
        )
        self.assertContains(response, 'must be operational')
        craft.refresh_from_db()
        self.assertEqual(craft.status, 'MAINTENANCE')

        craft.status = 'OPERATIONAL'
        craft.save(update_fields=['status'])
        response = self.client.post(
            reverse('dashboard_portal:seacraft_dispatch'),
            {
                'action': 'deploy_vehicle',
                'vehicle_id': craft.id,
                'driver_id': land_operator.id,
                'deployment_location': 'Honda Bay',
                'deployment_purpose': 'Emergency Search & Rescue',
                'deployment_time': '2030-01-02T10:30',
            },
            follow=True,
        )
        self.assertContains(response, 'qualified seacraft operator')
        craft.refresh_from_db()
        self.assertEqual(craft.status, 'OPERATIONAL')

    def test_operator_can_be_reassigned_from_maintenance_and_return_clears_deployment(self):
        repair_craft = self.create_vehicle(
            model_name='Maintenance Craft',
            plate_number='SEA-MAINT-01',
            vehicle_type=self.marine_type,
            status='MAINTENANCE',
            assigned_driver=self.operator,
        )
        operational_craft = self.create_vehicle(
            model_name='Ready Craft',
            plate_number='SEA-READY-01',
            vehicle_type=self.maritime_type,
        )
        self.client.force_login(self.seacraft_user)

        response = self.client.post(
            reverse('dashboard_portal:seacraft_dispatch'),
            {
                'action': 'deploy_vehicle',
                'vehicle_id': operational_craft.id,
                'driver_id': self.operator.id,
                'deployment_location': 'Honda Bay',
                'deployment_purpose': 'Emergency Search & Rescue',
                'deployment_time': '2030-01-02T10:30',
            },
        )
        self.assertRedirects(response, reverse('dashboard_portal:seacraft_dispatch'))
        repair_craft.refresh_from_db()
        operational_craft.refresh_from_db()
        self.assertIsNone(repair_craft.assigned_driver)
        self.assertEqual(operational_craft.assigned_driver, self.operator)

        response = self.client.post(
            reverse('dashboard_portal:seacraft_dispatch'),
            {'action': 'return_vehicle', 'vehicle_id': operational_craft.id},
        )
        self.assertRedirects(response, reverse('dashboard_portal:seacraft_dispatch'))
        operational_craft.refresh_from_db()
        self.assertEqual(operational_craft.status, 'OPERATIONAL')
        self.assertIsNone(operational_craft.deployment_location)
        self.assertIsNone(operational_craft.deployment_purpose)
        self.assertIsNone(operational_craft.deployment_time)
