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


import re
from django.core import mail
from django.test import override_settings


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AccountRecoveryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='reset@example.com', username='reset', password='OldPass123!')
        self.client = APIClient()

    def request_code(self):
        res = self.client.post('/api/auth/password-reset/', {'email': 'Reset@Example.com'}, format='json')
        self.assertEqual(res.status_code, 200)
        return re.search(r'\b(\d{6})\b', mail.outbox[-1].body).group(1)

    def test_reset_with_valid_code(self):
        code = self.request_code()
        res = self.client.post('/api/auth/password-reset/confirm/', {
            'email': 'reset@example.com', 'code': code, 'new_password': 'BrandNew456!',
        }, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('BrandNew456!'))
        # Codes are single-use.
        res = self.client.post('/api/auth/password-reset/confirm/', {
            'email': 'reset@example.com', 'code': code, 'new_password': 'Another789!',
        }, format='json')
        self.assertEqual(res.status_code, 400)

    def test_unknown_email_gets_same_reply_and_no_mail(self):
        res = self.client.post('/api/auth/password-reset/', {'email': 'nobody@example.com'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_code_locks_after_too_many_wrong_attempts(self):
        code = self.request_code()
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(5):
            self.client.post('/api/auth/password-reset/confirm/', {
                'email': 'reset@example.com', 'code': wrong, 'new_password': 'BrandNew456!',
            }, format='json')
        res = self.client.post('/api/auth/password-reset/confirm/', {
            'email': 'reset@example.com', 'code': code, 'new_password': 'BrandNew456!',
        }, format='json')
        self.assertEqual(res.status_code, 400)

    def test_delete_account_requires_password(self):
        self.client.force_authenticate(self.user)
        res = self.client.post('/api/auth/delete-account/', {'password': 'wrong'}, format='json')
        self.assertEqual(res.status_code, 400)
        res = self.client.post('/api/auth/delete-account/', {'password': 'OldPass123!'}, format='json')
        self.assertEqual(res.status_code, 204)
        self.assertFalse(User.objects.filter(email='reset@example.com').exists())
