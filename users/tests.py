from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from users.models import User

class AuthValidationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.existing_user = User.objects.create_user(
            email="test.athlete@example.com",
            username="test.athlete@example.com",
            password="StrongPassword123!",
            first_name="Marcus",
            last_name="Aurelius"
        )

    # --- Login Validation Tests ---
    def test_login_success(self):
        response = self.client.post('/api/auth/login/', {
            'email': 'test.athlete@example.com',
            'password': 'StrongPassword123!'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertIn('user', response.data)
        self.assertEqual(response.data['user']['email'], 'test.athlete@example.com')

    def test_login_case_insensitive_email(self):
        response = self.client.post('/api/auth/login/', {
            'email': 'TEST.ATHLETE@EXAMPLE.COM',
            'password': 'StrongPassword123!'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)

    def test_login_trimmed_whitespace_email(self):
        response = self.client.post('/api/auth/login/', {
            'email': '   test.athlete@example.com   ',
            'password': 'StrongPassword123!'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)

    def test_login_missing_email(self):
        response = self.client.post('/api/auth/login/', {
            'email': '',
            'password': 'StrongPassword123!'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue('email' in response.data or 'non_field_errors' in response.data or 'detail' in response.data)

    def test_login_invalid_email_format(self):
        response = self.client.post('/api/auth/login/', {
            'email': 'not-an-email',
            'password': 'StrongPassword123!'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue('email' in response.data or 'non_field_errors' in response.data or 'detail' in response.data)

    def test_login_missing_password(self):
        response = self.client.post('/api/auth/login/', {
            'email': 'test.athlete@example.com',
            'password': ''
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)

    def test_login_wrong_password(self):
        response = self.client.post('/api/auth/login/', {
            'email': 'test.athlete@example.com',
            'password': 'WrongPassword999!'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)

    def test_login_inactive_user(self):
        self.existing_user.is_active = False
        self.existing_user.save()
        response = self.client.post('/api/auth/login/', {
            'email': 'test.athlete@example.com',
            'password': 'StrongPassword123!'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)

    # --- Registration Validation Tests ---
    def test_register_success(self):
        response = self.client.post('/api/auth/register/', {
            'first_name': 'Sarah',
            'last_name': 'Connor',
            'email': 'sarah.connor@example.com',
            'password': 'T800Destroyer1!',
            'confirm_password': 'T800Destroyer1!'
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('tokens', response.data)
        self.assertIn('user', response.data)
        self.assertEqual(response.data['user']['email'], 'sarah.connor@example.com')
        self.assertTrue(User.objects.filter(email='sarah.connor@example.com').exists())

    def test_register_missing_first_name(self):
        response = self.client.post('/api/auth/register/', {
            'first_name': '',
            'last_name': 'Connor',
            'email': 'sarah2@example.com',
            'password': 'T800Destroyer1!'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('first_name', response.data)

    def test_register_short_first_name(self):
        response = self.client.post('/api/auth/register/', {
            'first_name': 'A',
            'last_name': 'Connor',
            'email': 'sarah3@example.com',
            'password': 'T800Destroyer1!'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('first_name', response.data)

    def test_register_invalid_email_format(self):
        response = self.client.post('/api/auth/register/', {
            'first_name': 'Sarah',
            'last_name': 'Connor',
            'email': 'invalid-email-address',
            'password': 'T800Destroyer1!'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data)

    def test_register_duplicate_email(self):
        response = self.client.post('/api/auth/register/', {
            'first_name': 'Marcus',
            'last_name': 'Clone',
            'email': 'test.athlete@example.com',
            'password': 'StrongPassword123!'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data)

    def test_register_duplicate_case_insensitive_email(self):
        response = self.client.post('/api/auth/register/', {
            'first_name': 'Marcus',
            'last_name': 'Clone',
            'email': 'TEST.ATHLETE@EXAMPLE.COM',
            'password': 'StrongPassword123!'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data)

    def test_register_short_password(self):
        response = self.client.post('/api/auth/register/', {
            'first_name': 'Sarah',
            'last_name': 'Connor',
            'email': 'sarah4@example.com',
            'password': 'Short1!'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)

    def test_register_numeric_only_password(self):
        response = self.client.post('/api/auth/register/', {
            'first_name': 'Sarah',
            'last_name': 'Connor',
            'email': 'sarah5@example.com',
            'password': '1234567890'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)

    def test_register_password_mismatch(self):
        response = self.client.post('/api/auth/register/', {
            'first_name': 'Sarah',
            'last_name': 'Connor',
            'email': 'sarah6@example.com',
            'password': 'T800Destroyer1!',
            'confirm_password': 'DifferentPassword1!'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('confirm_password', response.data)
