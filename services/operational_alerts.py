from datetime import timedelta
from decimal import Decimal

from accounts.models import User
from django.db.models import Q
from django.utils import timezone
from notifications.models import Notification
from notifications.services import create_notification

from .models import Service


UNASSIGNED_TITLE = 'Atama Bekleyen Servis'
OVERDUE_TITLE = 'Geciken Servis Uyarısı'
TECHNICIAN_OVERDUE_TITLE = 'Servis Durumu Güncelleme Hatırlatması'
RECEIVABLE_TITLE = 'Tahsilat Bekleyen Servis'
SERVICE_SCREEN = 'service_detail'


def _manager_users(tenant):
    return User.objects.filter(
        tenant=tenant,
        is_active=True,
    ).filter(
        Q(user_type='admin') | Q(is_staff=True) | Q(is_superuser=True)
    )


def _already_notified(user, title, service, notification_date):
    return Notification.objects.filter(
        user=user,
        title=title,
        related_id=str(service.id),
        created_at__date=notification_date,
    ).exists()


def _notify_once(user, title, message, service, notification_date):
    if _already_notified(user, title, service, notification_date):
        return False
    create_notification(
        user=user,
        title=title,
        message=message,
        related_id=str(service.id),
        related_screen=SERVICE_SCREEN,
    )
    return True


def _service_context(service):
    appointment = timezone.localtime(service.scheduled_date).strftime('%d.%m.%Y %H:%M')
    appointment_time = timezone.localtime(service.scheduled_date).strftime('%H:%M')
    customer = service.customer_full_name or 'Müşteri'
    address = str(service.customer_address or '').strip() or 'Adres bilgisi bulunmuyor'
    service_no = service.receipt_number or '-'
    return service_no, customer, address, appointment, appointment_time


def _format_amount(amount):
    value = Decimal(str(amount or 0)).quantize(Decimal('0.01'))
    return f"{value:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def _remaining_balance(service):
    total = sum(Decimal(str(item.total_price or 0)) for item in service.items.all())
    paid = sum(Decimal(str(payment.amount or 0)) for payment in service.payments.all())
    return max(total - paid, Decimal('0.00'))


def send_operational_alerts(
    now=None,
    include_unassigned=True,
    include_overdue_manager_alerts=True,
    include_technician_status_reminders=True,
    include_receivable=True,
):
    """Send once-daily operational alerts for selected service conditions."""
    now = timezone.localtime(now or timezone.now())
    today = now.date()
    sent = {'unassigned': 0, 'overdue': 0, 'receivable': 0}

    if include_unassigned:
        unassigned_services = Service.objects.filter(
            scheduled_date__date=today,
            technician__isnull=True,
        ).exclude(
            status__code__in=['cancelled', 'completed'],
        ).select_related('tenant')
        for service in unassigned_services:
            service_no, customer, address, appointment, _ = _service_context(service)
            message = (
                f"#{service_no} no'lu servis henüz bir teknisyene atanmadı.\n"
                f"Müşteri: {customer}\nAdres: {address}\nRandevu: {appointment}"
            )
            for manager in _manager_users(service.tenant):
                sent['unassigned'] += _notify_once(manager, UNASSIGNED_TITLE, message, service, today)

    if include_overdue_manager_alerts or include_technician_status_reminders:
        overdue_services = Service.objects.filter(
            scheduled_date__lt=now,
        ).exclude(
            status__code__in=['cancelled', 'completed'],
        ).select_related('tenant', 'technician__user')
        for service in overdue_services:
            service_no, customer, address, appointment, appointment_time = _service_context(service)
            manager_message = (
                f"#{service_no} no'lu servis planlanan saati geçti ancak durumu henüz tamamlanmadı.\n"
                f"Müşteri: {customer}\nAdres: {address}\nRandevu: {appointment}"
            )
            if include_overdue_manager_alerts:
                for manager in _manager_users(service.tenant):
                    sent['overdue'] += _notify_once(manager, OVERDUE_TITLE, manager_message, service, today)

            technician_user = getattr(getattr(service, 'technician', None), 'user', None)
            if include_technician_status_reminders and technician_user and technician_user.is_active:
                technician_message = (
                    f"{customer} adlı müşteriye ait, {address} adresinde "
                    f"{appointment_time} saatinde planlanan servis hatırlatması."
                )
                sent['overdue'] += _notify_once(
                    technician_user,
                    TECHNICIAN_OVERDUE_TITLE,
                    technician_message,
                    service,
                    today,
                )

    if include_receivable:
        receivable_services = Service.objects.filter(
            scheduled_date__lt=now,
            status__code='completed',
        ).select_related('tenant').prefetch_related('items', 'payments')
        for service in receivable_services:
            remaining = _remaining_balance(service)
            if remaining <= 0:
                continue
            service_no, customer, address, appointment, _ = _service_context(service)
            message = (
                f"#{service_no} no'lu tamamlanan servisin kalan tahsilat tutarı "
                f"{_format_amount(remaining)} TL.\nMüşteri: {customer}\n"
                f"Adres: {address}\nRandevu: {appointment}"
            )
            for manager in _manager_users(service.tenant):
                sent['receivable'] += _notify_once(manager, RECEIVABLE_TITLE, message, service, today)

    return {**sent, 'date': today, 'total_sent': sum(sent.values())}