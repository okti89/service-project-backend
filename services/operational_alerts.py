from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from accounts.models import User
from django.db.models import Q
from django.utils import timezone
from notifications.services import create_notification_once

from .models import Service


UNASSIGNED_TITLE = 'Atama Bekleyen Servis'
OVERDUE_TITLE = 'Geciken Servis Uyarısı'
TECHNICIAN_SCHEDULED_TITLE = 'Planlanan Servis Hatırlatması'
TECHNICIAN_OVERDUE_TITLE = 'Servis Durumu Güncelleme Hatırlatması'
RECEIVABLE_TITLE = 'Tahsilat Bekleyen Servis'
SERVICE_SCREEN = 'service_detail'


def _manager_users(tenant):
    return User.objects.filter(tenant=tenant, is_active=True).filter(
        Q(user_type='admin') | Q(is_staff=True) | Q(is_superuser=True)
    )


def _notify_once(user, title, message, dedupe_key, related_id=None, related_screen=SERVICE_SCREEN):
    _, created = create_notification_once(
        user=user,
        title=title,
        message=message,
        dedupe_key=dedupe_key,
        related_id=related_id,
        related_screen=related_screen,
    )
    return int(created)


def _service_context(service):
    local_scheduled = timezone.localtime(service.scheduled_date)
    return (
        service.receipt_number or '-',
        service.customer_full_name or 'Müşteri',
        str(service.customer_address or '').strip() or 'Adres bilgisi bulunmuyor',
        local_scheduled.strftime('%d.%m.%Y %H:%M'),
        local_scheduled.strftime('%H:%M'),
    )


def _format_amount(amount):
    value = Decimal(str(amount or 0)).quantize(Decimal('0.01'))
    return f"{value:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def _remaining_balance(service):
    total = sum(Decimal(str(item.total_price or 0)) for item in service.items.all())
    paid = sum(Decimal(str(payment.amount or 0)) for payment in service.payments.all())
    return max(total - paid, Decimal('0.00'))


def _overdue_customer_summary(services, limit=5):
    names = [service.customer_full_name or 'Müşteri' for service in services[:limit]]
    summary = ', '.join(names)
    remaining_count = len(services) - len(names)
    if remaining_count > 0:
        summary = f'{summary} ve {remaining_count} servis daha'
    return summary


def _active_service_queryset():
    return Service.objects.exclude(status__code__in=['cancelled', 'completed'])


def send_operational_alerts(
    now=None,
    include_unassigned=True,
    include_overdue_manager_alerts=True,
    include_technician_schedule_reminders=True,
    include_technician_status_reminders=True,
    include_receivable=True,
):
    """Send once-daily operational alerts for selected service conditions."""
    now = timezone.localtime(now or timezone.now())
    today = now.date()
    sent = {'unassigned': 0, 'scheduled': 0, 'overdue': 0, 'receivable': 0}

    if include_unassigned:
        services = _active_service_queryset().filter(scheduled_date__date=today, technician__isnull=True).select_related('tenant')
        for service in services:
            service_no, customer, address, appointment, _ = _service_context(service)
            message = f"#{service_no} no'lu servis henüz bir teknisyene atanmadı.\nMüşteri: {customer}\nAdres: {address}\nRandevu: {appointment}"
            for manager in _manager_users(service.tenant):
                sent['unassigned'] += _notify_once(
                    manager,
                    UNASSIGNED_TITLE,
                    message,
                    f'operational:unassigned:{service.id}:{today.isoformat()}',
                    related_id=str(service.id),
                )

    if include_technician_schedule_reminders:
        services = _active_service_queryset().filter(
            scheduled_date__lte=now,
            scheduled_date__gt=now - timedelta(minutes=30),
            technician__isnull=False,
        ).select_related('tenant', 'technician__user')
        for service in services:
            _, customer, address, _, appointment_time = _service_context(service)
            technician_user = getattr(getattr(service, 'technician', None), 'user', None)
            if technician_user and technician_user.is_active and technician_user.tenant_id == service.tenant_id:
                message = f"{customer} adlı müşteriye ait, {address} adresinde {appointment_time} saatinde planlanan servis hatırlatması."
                sent['scheduled'] += _notify_once(
                    technician_user,
                    TECHNICIAN_SCHEDULED_TITLE,
                    message,
                    f'operational:scheduled:{service.id}',
                    related_id=str(service.id),
                )

    if include_overdue_manager_alerts or include_technician_status_reminders:
        services = list(
            _active_service_queryset()
            .filter(scheduled_date__lt=now)
            .select_related('tenant', 'technician__user')
            .order_by('scheduled_date')
        )

        if include_overdue_manager_alerts:
            services_by_tenant = defaultdict(list)
            for service in services:
                if service.tenant_id:
                    services_by_tenant[service.tenant_id].append(service)

            for tenant_services in services_by_tenant.values():
                tenant = tenant_services[0].tenant
                service_count = len(tenant_services)
                oldest_appointment = _service_context(tenant_services[0])[3]
                customer_summary = _overdue_customer_summary(tenant_services)
                manager_message = (
                    f"Şu anda {service_count} geciken servis bulunuyor. "
                    f"Müşteriler: {customer_summary}. "
                    f"En eski randevu: {oldest_appointment}. Listeyi kontrol ederek ekibi yönlendirebilirsiniz."
                )
                for manager in _manager_users(tenant):
                    sent['overdue'] += _notify_once(
                        manager,
                        OVERDUE_TITLE,
                        manager_message,
                        f'operational:manager-overdue:{tenant.id}:{today.isoformat()}',
                        related_screen='overdue_services',
                    )

        for service in services:
            _, customer, address, _, appointment_time = _service_context(service)
            appointment_date = timezone.localtime(service.scheduled_date).strftime('%d.%m.%Y')
            technician_user = getattr(getattr(service, 'technician', None), 'user', None)
            if (
                include_technician_status_reminders
                and service.scheduled_date <= now - timedelta(minutes=30)
                and technician_user
                and technician_user.is_active
                and technician_user.tenant_id == service.tenant_id
            ):
                message = (
                    f"{customer} adlı müşteriye ait, {address} adresinde {appointment_date} tarihinde "
                    f"{appointment_time} saatinde planlanan servis için durum hatırlatması."
                )
                sent['overdue'] += _notify_once(
                    technician_user,
                    TECHNICIAN_OVERDUE_TITLE,
                    message,
                    f'operational:technician-overdue:{service.id}',
                    related_id=str(service.id),
                )

    if include_receivable:
        services = Service.objects.filter(scheduled_date__lt=now, status__code='completed').select_related('tenant').prefetch_related('items', 'payments')
        for service in services:
            remaining = _remaining_balance(service)
            if remaining <= 0:
                continue
            service_no, customer, address, appointment, _ = _service_context(service)
            message = f"#{service_no} no'lu tamamlanan servisin kalan tahsilat tutarı {_format_amount(remaining)} TL.\nMüşteri: {customer}\nAdres: {address}\nRandevu: {appointment}"
            for manager in _manager_users(service.tenant):
                sent['receivable'] += _notify_once(
                    manager,
                    RECEIVABLE_TITLE,
                    message,
                    f'operational:receivable:{service.id}:{today.isoformat()}',
                    related_id=str(service.id),
                )

    return {**sent, 'date': today, 'total_sent': sum(sent.values())}
