from django.contrib.auth.models import Group, User
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from .models import Vehicle, VehicleType


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

    def test_seacraft_dispatch_uses_grid_and_shows_pending_reason_in_status_order(self):
        user = User.objects.create_user(username='seacraft_dispatcher', password='SecurePass123!')
        marine_type = VehicleType.objects.create(name='MARINE')
        created_vessels = []
        for index, status in enumerate(
            ['MAINTENANCE', 'PENDING_DISPOSAL', 'DEPLOYED', 'OPERATIONAL'],
            start=1,
        ):
            created_vessels.append(
                Vehicle.objects.create(
                    model_name=f'Vessel {status}',
                    plate_number=f'DSP-{index:04d}',
                    vehicle_type=marine_type,
                    status=status,
                )
            )
        pending_vessel = created_vessels[1]
        LogEntry.objects.create(
            user=user,
            content_type=ContentType.objects.get_for_model(Vehicle),
            object_id=str(pending_vessel.id),
            object_repr=str(pending_vessel),
            action_flag=CHANGE,
            change_message='Flagged maritime asset. Remarks: Hull damage found.',
        )
        self.client.force_login(user)

        response = self.client.get(reverse('dashboard_portal:seacraft_dispatch'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context['sea_crafts'].values_list('status', flat=True)),
            ['OPERATIONAL', 'DEPLOYED', 'MAINTENANCE', 'PENDING_DISPOSAL'],
        )
        self.assertContains(response, 'fleet/css/asset_grid.css')
        self.assertContains(response, 'Hull damage found.')
        self.assertContains(response, 'asset-grid-table--sea')

    def test_land_disposal_reason_is_visible_before_archiving(self):
        group = Group.objects.create(name='Logistics Officers')
        user = User.objects.create_user(username='logistics_user', password='SecurePass123!')
        user.groups.add(group)
        vehicle_type = VehicleType.objects.create(name='Truck')
        vehicle = Vehicle.objects.create(
            model_name='Rescue Truck 01',
            plate_number='ABC-1234',
            vehicle_type=vehicle_type,
            status='PENDING_DISPOSAL',
        )
        LogEntry.objects.create(
            user=user,
            content_type=ContentType.objects.get_for_model(Vehicle),
            object_id=str(vehicle.id),
            object_repr=str(vehicle),
            action_flag=CHANGE,
            change_message='Flagged asset for disposal. Remarks: Engine damage beyond repair.',
        )

        self.client.force_login(user)
        response = self.client.get(reverse('dashboard_portal:logistics_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Disposal reason:')
        self.assertContains(response, 'Engine damage beyond repair.')

    def test_logistics_dashboard_orders_both_divisions_and_shows_maritime_disposal_reason(self):
        group = Group.objects.create(name='Logistics Officers')
        user = User.objects.create_user(username='logistics_user', password='SecurePass123!')
        user.groups.add(group)
        land_type = VehicleType.objects.create(name='Truck')
        marine_type = VehicleType.objects.create(name='MARINE')
        status_order = [
            ('OPERATIONAL', 'Operational'),
            ('DEPLOYED', 'Deployed'),
            ('PENDING_DISPOSAL', 'Pending'),
            ('MAINTENANCE', 'Maintenance'),
        ]
        for index, (status, label) in enumerate(status_order, start=1):
            Vehicle.objects.create(
                model_name=f'{label} Land Vehicle',
                plate_number=f'LAND-{index:04d}',
                vehicle_type=land_type,
                status=status,
            )
            sea_vessel = Vehicle.objects.create(
                model_name=f'{label} Vessel',
                plate_number=f'SEA-{index:04d}',
                vehicle_type=marine_type,
                status=status,
            )
            if status == 'PENDING_DISPOSAL':
                LogEntry.objects.create(
                    user=user,
                    content_type=ContentType.objects.get_for_model(Vehicle),
                    object_id=str(sea_vessel.id),
                    object_repr=str(sea_vessel),
                    action_flag=CHANGE,
                    change_message='Flagged maritime asset. Remarks: Hull damage requires replacement.',
                )

        self.client.force_login(user)
        response = self.client.get(reverse('dashboard_portal:logistics_dashboard'))

        self.assertEqual(response.status_code, 200)
        expected_status_order = ['OPERATIONAL', 'DEPLOYED', 'MAINTENANCE', 'PENDING_DISPOSAL']
        self.assertEqual(
            list(response.context['land_vehicles'].values_list('status', flat=True)),
            expected_status_order,
        )
        self.assertEqual(
            list(response.context['sea_crafts'].values_list('status', flat=True)),
            expected_status_order,
        )
        self.assertContains(response, 'Hull damage requires replacement.')
        self.assertEqual(response.content.count(b'class="asset-grid"'), 2)
        self.assertContains(response, 'fleet/images/land-vehicle.svg')
        self.assertContains(response, 'fleet/images/seacraft.svg')
        self.assertContains(response, 'Operational Land Vehicle')
        self.assertContains(response, 'Operational Vessel')

    def test_mechanic_can_see_disposal_reason_and_undo_pending_disposal(self):
        group = Group.objects.create(name='Technicians')
        user = User.objects.create_user(username='mechanic_user', password='SecurePass123!')
        user.groups.add(group)
        vehicle_type = VehicleType.objects.create(name='Truck')
        vehicle = Vehicle.objects.create(
            model_name='Rescue Truck 02',
            plate_number='DEF-5678',
            vehicle_type=vehicle_type,
            status='PENDING_DISPOSAL',
        )
        LogEntry.objects.create(
            user=user,
            content_type=ContentType.objects.get_for_model(Vehicle),
            object_id=str(vehicle.id),
            object_repr=str(vehicle),
            action_flag=CHANGE,
            change_message='Flagged asset for disposal. Remarks: Transmission failure.',
        )
        self.client.force_login(user)

        response = self.client.get(reverse('dashboard_portal:repairman_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PENDING DISPOSAL')
        self.assertContains(response, 'Transmission failure.')
        self.assertContains(response, 'Undo Disposal')

        response = self.client.post(
            reverse('dashboard_portal:repairman_dashboard'),
            {'vehicle_id': vehicle.id, 'action_type': 'UNDO_DISPOSAL'},
        )

        self.assertRedirects(response, reverse('dashboard_portal:repairman_dashboard'))
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, 'MAINTENANCE')

    def test_mechanic_can_update_pending_disposal_reason(self):
        group = Group.objects.create(name='Technicians')
        user = User.objects.create_user(username='mechanic_user', password='SecurePass123!')
        user.groups.add(group)
        vehicle_type = VehicleType.objects.create(name='Truck')
        vehicle = Vehicle.objects.create(
            model_name='Rescue Truck 03',
            plate_number='GHI-9012',
            vehicle_type=vehicle_type,
            status='PENDING_DISPOSAL',
        )
        LogEntry.objects.create(
            user=user,
            content_type=ContentType.objects.get_for_model(Vehicle),
            object_id=str(vehicle.id),
            object_repr=str(vehicle),
            action_flag=CHANGE,
            change_message='Flagged asset for disposal. Remarks: Initial engine fault.',
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse('dashboard_portal:repairman_dashboard'),
            {
                'vehicle_id': vehicle.id,
                'action_type': 'UPDATE_DISPOSAL_REASON',
                'disposal_remarks': 'Engine damage confirmed beyond repair.',
            },
        )

        self.assertRedirects(response, reverse('dashboard_portal:repairman_dashboard'))
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, 'PENDING_DISPOSAL')
        updated_log = LogEntry.objects.filter(
            object_id=str(vehicle.id),
            change_message__contains='Updated disposal reason',
        ).latest('action_time')
        self.assertIn('Engine damage confirmed beyond repair.', updated_log.change_message)

        response = self.client.get(reverse('dashboard_portal:repairman_dashboard'))
        self.assertContains(response, 'Engine damage confirmed beyond repair.')
        self.assertNotContains(response, 'Initial engine fault.')

    def test_mechanical_workbench_orders_vehicles_by_status_priority(self):
        group = Group.objects.create(name='Technicians')
        user = User.objects.create_user(username='mechanic_user', password='SecurePass123!')
        user.groups.add(group)
        vehicle_type = VehicleType.objects.create(name='Truck')
        status_order = [
            ('OPERATIONAL', 'Operational vehicle'),
            ('DEPLOYED', 'Deployed vehicle'),
            ('PENDING_DISPOSAL', 'Pending vehicle'),
            ('MAINTENANCE', 'Maintenance vehicle'),
        ]
        for index, (status, model_name) in enumerate(status_order, start=1):
            Vehicle.objects.create(
                model_name=model_name,
                plate_number=f'TEST-{index:04d}',
                vehicle_type=vehicle_type,
                status=status,
            )

        self.client.force_login(user)
        response = self.client.get(reverse('dashboard_portal:repairman_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context['vehicles'].values_list('status', flat=True)),
            ['OPERATIONAL', 'DEPLOYED', 'MAINTENANCE', 'PENDING_DISPOSAL'],
        )

    def test_seacraft_workbench_orders_vehicles_by_status_priority(self):
        group = Group.objects.create(name='Maritime_Tech')
        user = User.objects.create_user(username='maritime_tech', password='SecurePass123!')
        user.groups.add(group)
        marine_type = VehicleType.objects.create(name='MARINE')
        status_order = [
            ('OPERATIONAL', 'Operational vessel'),
            ('DEPLOYED', 'Deployed vessel'),
            ('PENDING_DISPOSAL', 'Pending vessel'),
            ('MAINTENANCE', 'Maintenance vessel'),
        ]
        for index, (status, model_name) in enumerate(status_order, start=1):
            Vehicle.objects.create(
                model_name=model_name,
                plate_number=f'SEA-{index:04d}',
                vehicle_type=marine_type,
                status=status,
            )

        self.client.force_login(user)
        response = self.client.get(reverse('dashboard_portal:seacraft_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context['vehicles'].values_list('status', flat=True)),
            ['OPERATIONAL', 'DEPLOYED', 'MAINTENANCE', 'PENDING_DISPOSAL'],
        )

    def test_maritime_mechanic_can_update_disposal_reason_and_undo(self):
        group = Group.objects.create(name='Maritime_Tech')
        user = User.objects.create_user(username='maritime_tech', password='SecurePass123!')
        user.groups.add(group)
        marine_type = VehicleType.objects.create(name='MARINE')
        vessel = Vehicle.objects.create(
            model_name='Rescue Vessel 01',
            plate_number='SEA-1001',
            vehicle_type=marine_type,
            status='PENDING_DISPOSAL',
        )
        LogEntry.objects.create(
            user=user,
            content_type=ContentType.objects.get_for_model(Vehicle),
            object_id=str(vessel.id),
            object_repr=str(vessel),
            action_flag=CHANGE,
            change_message='Flagged maritime asset for disposal. Remarks: Initial hull damage.',
        )
        self.client.force_login(user)

        response = self.client.get(reverse('dashboard_portal:seacraft_dashboard'))
        self.assertContains(response, 'Initial hull damage.')
        self.assertContains(response, 'Undo Disposal')

        response = self.client.post(
            reverse('dashboard_portal:seacraft_dashboard'),
            {
                'vehicle_id': vessel.id,
                'action_type': 'UPDATE_DISPOSAL_REASON',
                'disposal_remarks': 'Hull integrity compromised.',
            },
        )
        self.assertRedirects(response, reverse('dashboard_portal:seacraft_dashboard'))
        response = self.client.get(reverse('dashboard_portal:seacraft_dashboard'))
        self.assertContains(response, 'Hull integrity compromised.')
        self.assertNotContains(response, 'Initial hull damage.')

        response = self.client.post(
            reverse('dashboard_portal:seacraft_dashboard'),
            {'vehicle_id': vessel.id, 'action_type': 'UNDO_DISPOSAL'},
        )
        self.assertRedirects(response, reverse('dashboard_portal:seacraft_dashboard'))
        vessel.refresh_from_db()
        self.assertEqual(vessel.status, 'MAINTENANCE')
