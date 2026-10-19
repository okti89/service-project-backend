from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import User, UserDevice
from accounts.reminder_services import send_pending_approval_reminders
from tenants.models import Tenant


class UserDeviceTenantSyncTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(name="Tenant A", code="tenant-a")
        self.user = User.objects.create_user(
            email="tech@example.com",
            password="test123",
            user_type="technician",
            tenant=self.tenant,
        )
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def test_register_device_sets_tenant_from_authenticated_user(self):
        response = self.client.post(
            "/api/accounts/devices/register/",
            {
                "token": "ExponentPushToken[test-token]",
                "device_id": "device-1",
                "device_name": "Pixel",
                "platform": "android",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        device = UserDevice.objects.get(expo_token="ExponentPushToken[test-token]")
        self.assertEqual(device.user, self.user)
        self.assertEqual(device.tenant, self.tenant)


    def test_register_device_persists_location_permission(self):
        response = self.client.post(
            "/api/accounts/devices/register/",
            {
                "token": "ExponentPushToken[location-token]",
                "device_id": "device-location",
                "device_name": "Pixel",
                "platform": "android",
                "location_permission": True,
                "notification_permission": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        device = UserDevice.objects.get(expo_token="ExponentPushToken[location-token]")
        self.assertTrue(device.location_permission)
        self.assertTrue(device.notification_permission)

    def test_save_backfills_tenant_when_user_gets_tenant_later(self):
        delayed_user = User.objects.create_user(
            email="later@example.com",
            password="test123",
            user_type="technician",
        )
        device = UserDevice.objects.create(
            user=delayed_user,
            expo_token="ExponentPushToken[later-token]",
            device_name="iPhone",
            platform="ios",
        )

        self.assertIsNone(device.tenant)

        delayed_user.tenant = self.tenant
        delayed_user.save(update_fields=["tenant"])

        device.notification_permission = True
        device.save()
        device.refresh_from_db()

        self.assertEqual(device.tenant, self.tenant)


class AccountTenantIsolationTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Account A", code="account-a")
        self.other_tenant = Tenant.objects.create(name="Account B", code="account-b")
        self.admin = User.objects.create_user(
            email="account-admin@example.com",
            password="pass123",
            tenant=self.tenant,
            user_type="admin",
        )
        self.other_user = User.objects.create_user(
            email="account-other@example.com",
            password="pass123",
            tenant=self.other_tenant,
            user_type="technician",
        )

    def test_authenticated_user_creation_ignores_forged_tenant_header(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        response = client.post(
            "/api/accounts/admin/users/",
            {
                "email": "created-by-admin@example.com",
                "password": "pass12345",
                "first_name": "Created",
                "user_type": "technician",
            },
            format="json",
            HTTP_X_TENANT_CODE=self.other_tenant.code,
        )

        self.assertEqual(response.status_code, 201, response.data)
        created = User.objects.get(email="created-by-admin@example.com")
        self.assertEqual(created.tenant, self.tenant)

    def test_login_does_not_fall_back_to_another_tenant_when_code_is_supplied(self):
        response = APIClient().post(
            "/api/accounts/auth/login/",
            {"email": self.other_user.email, "password": "pass123"},
            format="json",
            HTTP_X_TENANT_CODE=self.tenant.code,
        )

        self.assertEqual(response.status_code, 400)


class AccountDeletionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(name="Tenant B", code="tenant-b")
        self.user = User.objects.create_user(email="delete@example.com", password="delete-pass-123", user_type="technician", tenant=self.tenant)
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def test_delete_account_requires_password_and_removes_user(self):
        response = self.client.delete('/api/accounts/auth/delete-account/', {"password": "delete-pass-123", "confirmation": "SİL"}, format="json")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())


class PendingApprovalReminderTests(TestCase):
    @override_settings(PENDING_APPROVAL_REMINDER_EMAIL_ENABLED=False)
    @patch('accounts.reminder_services.send_admin_pending_approval_reminder_email')
    @patch('accounts.reminder_services.create_notification')
    def test_reminder_email_is_disabled_while_in_app_notification_continues(
        self,
        create_notification_mock,
        send_email_mock,
    ):
        tenant = Tenant.objects.create(name='Tenant C', code='tenant-c')
        User.objects.create_user(
            email='admin@example.com',
            password='test123',
            user_type='admin',
            is_staff=True,
            approval_status='approved',
            tenant=tenant,
        )
        User.objects.create_user(
            email='pending@example.com',
            password='test123',
            user_type='technician',
            approval_status='pending',
            tenant=tenant,
        )

        sent_count = send_pending_approval_reminders()

        self.assertEqual(sent_count, 1)
        create_notification_mock.assert_called_once()
        send_email_mock.assert_not_called()


class PersonnelRegistrationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(name='Personnel Test', code='personnel-test')
        self.notification_patch = patch('accounts.views.create_notification')
        self.notification_patch.start()
        self.addCleanup(self.notification_patch.stop)

    def register(self, email, **extra):
        payload = {
            'tenant_code': self.tenant.code,
            'email': email,
            'password': 'PersonnelTest2026!',
            'first_name': 'Test', 'last_name': 'Employee',
            **extra,
        }
        return self.client.post('/api/accounts/auth/register/', payload, format='json')

    def test_multiple_employees_can_register_with_omitted_blank_or_null_phone(self):
        for i, extra in enumerate(({}, {'phone_number': ''}, {'phone_number': None}, {'phone_number': '   '})):
            with self.subTest(extra=extra):
                response = self.register(f'no-phone-{i}@example.com', **extra)
                self.assertEqual(response.status_code, 201, response.data)
                user = User.objects.get(email=f'no-phone-{i}@example.com')
                self.assertIsNone(user.phone_number)
                self.assertEqual(user.tenant, self.tenant)
                self.assertEqual(user.approval_status, 'pending')
                self.assertEqual(user.user_type, 'technician')

    def test_provided_phone_is_preserved_and_duplicates_are_rejected(self):
        response = self.register('phone@example.com', phone_number='05420000001')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(User.objects.get(email='phone@example.com').phone_number, '05420000001')
        duplicate = self.register('duplicate@example.com', phone_number='05420000001')
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn('phone_number', duplicate.data)

    def test_company_code_is_still_required_and_invalid_code_is_rejected(self):
        for code in ('', 'missing-company'):
            response = self.register('invalid@example.com', tenant_code=code)
            self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email='invalid@example.com').exists())

    def test_registration_cannot_request_admin_role_or_self_approval(self):
        response = self.register('pending@example.com', user_type='admin', approval_status='approved', is_staff=True)
        self.assertEqual(response.status_code, 201, response.data)
        user = User.objects.get(email='pending@example.com')
        self.assertEqual(user.user_type, 'technician')
        self.assertEqual(user.approval_status, 'pending')
        self.assertFalse(user.is_staff)
        self.assertFalse(hasattr(user, 'technician_profile'))
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + response.data['token'])
        check = self.client.get('/api/accounts/auth/check/')
        self.assertEqual(check.status_code, 403)
        self.assertEqual(check.data['account_status'], 'pending')

    @patch('accounts.views.send_approval_email')
    def test_admin_can_approve_employee_registered_without_phone(self, send_email):
        response = self.register('approve-me@example.com')
        self.assertEqual(response.status_code, 201, response.data)
        user = User.objects.get(email='approve-me@example.com')
        admin = User.objects.create_user(email='admin@example.com', password='AdminTest2026!', tenant=self.tenant, user_type='admin', approval_status='approved')
        self.client.force_authenticate(user=admin)
        approval = self.client.patch(f'/api/accounts/admin/users/{user.id}/', {'approval_status': 'approved'}, format='json')
        self.assertEqual(approval.status_code, 200, approval.data)
        user.refresh_from_db()
        self.assertEqual(user.approval_status, 'approved')
        self.assertIsNone(user.phone_number)
        self.assertTrue(hasattr(user, 'technician_profile'))
        self.client.force_authenticate(user=None)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + response.data['token'])
        self.assertEqual(self.client.get('/api/accounts/auth/check/').status_code, 200)

    def test_nonempty_phone_still_obeys_length_limit(self):
        response = self.register('long-phone@example.com', phone_number='1' * 16)
        self.assertEqual(response.status_code, 400)
        self.assertIn('phone_number', response.data)

    def test_editing_multiple_employees_without_phone_keeps_null(self):
        for i in range(2):
            response = self.register(f'edit-no-phone-{i}@example.com')
            self.assertEqual(response.status_code, 201, response.data)
            self.client.credentials(HTTP_AUTHORIZATION='Token ' + response.data['token'])
            edited = self.client.patch('/api/accounts/auth/me/', {'phone_number': ''}, format='json')
            self.assertEqual(edited.status_code, 200, edited.data)
            self.assertIsNone(User.objects.get(email=f'edit-no-phone-{i}@example.com').phone_number)
            self.client.credentials()
