from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from accounts.models import User, UserDevice
from notifications.models import Notification
from notifications.services import create_notification
from notifications.views import AdminSendNotificationView, NotificationView
from tenants.models import Tenant


class NotificationBehaviorTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.tenant = Tenant.objects.create(name="Tenant A", code="tenant-a")

        self.user = User.objects.create_user(
            email="tech@example.com",
            password="test123",
            tenant=self.tenant,
            user_type="technician",
        )
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="test123",
            tenant=self.tenant,
            user_type="admin",
        )

    def test_patch_marks_notification_as_read_with_timestamp(self):
        notification = Notification.objects.create(
            tenant=self.tenant,
            user=self.user,
            title="Test",
            message="Hello",
        )

        request = self.factory.patch(f"/api/notifications/notifications/{notification.pk}/")
        request.user = self.user

        response = NotificationView.as_view()(request, pk=notification.pk)

        notification.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(notification.is_read)
        self.assertIsNotNone(notification.read_at)

    @patch("notifications.services.send_expo_push_notification")
    def test_create_notification_attempts_push_when_user_is_active(self, mock_push):
        UserDevice.objects.create(
            tenant=self.tenant,
            user=self.user,
            expo_token="ExponentPushToken[test-token]",
        )

        notification = create_notification(
            user=self.user,
            title="Hello",
            message="World",
        )

        self.assertEqual(notification.user, self.user)
        mock_push.assert_called_once()

    @patch("notifications.views.send_mass_mail")
    @patch("notifications.services.send_bulk_expo_push_notification")
    def test_admin_send_creates_notifications_even_when_push_disabled(
        self,
        mock_bulk_push,
        mock_send_mail,
    ):
        request = self.factory.post(
            "/api/notifications/admin/notifications/send/",
            {
                "title": "Maintenance",
                "message": "Planned work",
                "user_ids": [str(self.user.id)],
                "send_to_all": False,
                "send_push": False,
                "send_email": False,
            },
            format="json",
        )
        request.user = self.admin

        response = AdminSendNotificationView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)
        mock_bulk_push.assert_not_called()
        mock_send_mail.assert_not_called()
