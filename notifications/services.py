from django.db import transaction

from .models import Notification
from .utils import send_bulk_expo_push_notification, send_expo_push_notification


def _build_push_data(related_id=None, related_screen=None):
    data = {}
    if related_screen:
        data["screen"] = related_screen
    if related_id:
        data["related_id"] = related_id
    return data or None


def create_notification(user, title, message, related_id=None, related_screen=None):
    tenant = getattr(user, "tenant", None)

    with transaction.atomic():
        notification = Notification.objects.create(
            tenant=tenant,
            user=user,
            title=title,
            message=message,
            related_id=related_id,
            related_screen=related_screen,
        )

    push_data = _build_push_data(related_id, related_screen)

    if getattr(user, "is_active", False):
        try:
            send_expo_push_notification(
                user=user,
                title=title,
                body=message,
                data=push_data,
            )
        except Exception:
            pass

    return notification


def create_bulk_notification(
    users,
    title,
    message,
    related_id=None,
    related_screen=None,
    send_push=True,
):
    users = list(users)

    if not users:
        return []

    tenant = getattr(users[0], "tenant", None)
    if not tenant:
        return []

    users = [user for user in users if getattr(user, "tenant_id", None) == tenant.id]
    if not users:
        return []

    push_data = _build_push_data(related_id, related_screen)

    notifications = [
        Notification(
            tenant=tenant,
            user=user,
            title=title,
            message=message,
            related_id=related_id,
            related_screen=related_screen,
        )
        for user in users
    ]

    with transaction.atomic():
        Notification.objects.bulk_create(notifications, batch_size=1000)

    if send_push:
        try:
            send_bulk_expo_push_notification(
                users=users,
                title=title,
                body=message,
                data=push_data,
            )
        except Exception:
            pass

    return notifications
