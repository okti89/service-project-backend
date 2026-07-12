from collections import defaultdict
from datetime import date

from accounts.models import User
from django.db.models import Count
from django.utils import timezone
from notifications.models import Notification
from notifications.services import create_notification

from .models import Service


SUMMARY_SCREEN = 'DailyServiceSummary'
SUMMARY_TITLE = 'Günlük Servis Özeti'


def _is_manager(user):
    return bool(user.is_superuser or user.is_staff or user.user_type == 'admin')


def _already_sent(user, summary_date):
    return Notification.objects.filter(
        user=user,
        related_screen=SUMMARY_SCREEN,
        related_id=summary_date.isoformat(),
    ).exists()


def _manager_message(name, service_count):
    greeting = 'Günaydın'
    if service_count:
        return (
            f"{greeting} {name}. Bugün için toplam {service_count} "
            f"aktif servis planlandı. Günün iş planını kontrol ederek ekibinizi yönlendirebilirsiniz."
        )
    return (
        f"{greeting} {name}. Bugün için planlanmış aktif servis bulunmuyor. "
        f"Yeni kayıtları gün içinde takip edebilirsiniz."
    )


def _technician_message(name, service_count):
    greeting = 'Günaydın'
    if service_count:
        return (
            f"{greeting} {name}. Bugün size atanmış {service_count} "
            f"servis bulunuyor. Randevu saatlerinizi ve adresleri kontrol ederek güne başlayabilirsiniz."
        )
    return (
        f"{greeting} {name}. Bugün size atanmış aktif servis bulunmuyor. "
        f"Gün içinde atanacak yeni servisleri takip edebilirsiniz."
    )


def send_daily_service_summaries(summary_date=None, force=False):
    """Create one daily service summary notification for each active recipient."""
    summary_date = summary_date or timezone.localdate()
    if not isinstance(summary_date, date):
        raise ValueError('summary_date must be a date instance.')

    today_services = Service.objects.filter(
        scheduled_date__date=summary_date,
    ).exclude(
        status__code='cancelled',
    )

    manager_counts = {
        row['tenant_id']: row['count']
        for row in today_services.values('tenant_id').annotate(count=Count('id'))
    }
    technician_counts = {
        (row['tenant_id'], row['technician__user_id']): row['count']
        for row in today_services.exclude(technician__isnull=True)
        .values('tenant_id', 'technician__user_id')
        .annotate(count=Count('id'))
    }

    sent_count = 0
    skipped_count = 0
    recipients = User.objects.filter(
        is_active=True,
        tenant__isnull=False,
    ).select_related('tenant')

    for user in recipients:
        if not force and _already_sent(user, summary_date):
            skipped_count += 1
            continue

        name = user.get_full_name()
        if _is_manager(user):
            message = _manager_message(name, manager_counts.get(user.tenant_id, 0))
        elif user.user_type == 'technician':
            message = _technician_message(
                name,
                technician_counts.get((user.tenant_id, user.id), 0),
            )
        else:
            continue

        create_notification(
            user=user,
            title=SUMMARY_TITLE,
            message=message,
            related_id=summary_date.isoformat(),
            related_screen=SUMMARY_SCREEN,
        )
        sent_count += 1

    return {'sent': sent_count, 'skipped': skipped_count, 'date': summary_date}
