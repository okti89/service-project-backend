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
