from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse


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
