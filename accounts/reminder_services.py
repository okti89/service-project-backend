from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from notifications.services import create_notification
from .models import User
from .utils import send_admin_pending_approval_reminder_email


def format_waiting_duration(total_hours):
    total_hours = max(1, int(total_hours))
    days = total_hours // 24
    hours = total_hours % 24

    if days > 0 and hours > 0:
        return f"{days} gün {hours} saat"
    if days > 0:
        return f"{days} gün"
    return f"{hours} saat"


def send_pending_approval_reminders(
    interval_hours=24,
    only_user_id=None,
    tenant=None
):

    now = timezone.now()
    min_next_at = now - timedelta(hours=max(1, int(interval_hours)))

    pending_users = User.objects.filter(
        approval_status='pending',
        is_active=True
    )

    if tenant:
        pending_users = pending_users.filter(tenant=tenant)

    if only_user_id:
        pending_users = pending_users.filter(id=only_user_id)
    else:
        pending_users = pending_users.filter(
            Q(pending_reminder_sent_at__isnull=True) |
            Q(pending_reminder_sent_at__lte=min_next_at)
        )

    sent_count = 0

    for pending_user in pending_users.select_related('tenant'):

        admins = User.objects.filter(
            Q(is_staff=True) | Q(user_type='admin'),
            is_active=True,
            tenant=pending_user.tenant
        ).exclude(id=pending_user.id)

        if not admins.exists():
            continue

        waiting_hours = max(
            1,
            int((now - pending_user.date_joined).total_seconds() // 3600)
        )

        waiting_label = format_waiting_duration(waiting_hours)

        for admin in admins.select_related('tenant'):

            create_notification(
                user=admin,
                title='Onay Bekleyen Kullanıcı',
                message=(
                    f"{pending_user.get_full_name()} "
                    f"({pending_user.email}) "
                    f"{waiting_label} süredir onay bekliyor."
                ),
                related_screen='UserDetail',
                related_id=str(pending_user.id),
            )

            try:
                send_admin_pending_approval_reminder_email(
                    admin_user=admin,
                    user_full_name=pending_user.get_full_name(),
                    user_email=pending_user.email,
                    waiting_label=waiting_label,
                )
            except Exception as e:
                # log önerilir
                print(f"Email error: {e}")

        pending_user.pending_reminder_sent_at = now
        pending_user.pending_reminder_count = (
            pending_user.pending_reminder_count or 0
        ) + 1

        pending_user.save(
            update_fields=[
                'pending_reminder_sent_at',
                'pending_reminder_count'
            ]
        )

        sent_count += 1

    return sent_count