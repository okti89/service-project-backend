from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from .models import CompanyConfig, HolidayException, WorkingHour
from notifications.services import create_bulk_notification
from technicians.models import Technician


@receiver(post_save, sender=CompanyConfig)
def create_default_working_hours(sender, instance, created, **kwargs):
    """
    CompanyConfig ilk oluşturulduğunda default çalışma saatlerini oluşturur.
    """
    if not created:
        return

    default_hours = [
        (0, "08:30", "18:00"),  # Pazartesi
        (1, "08:30", "18:00"),  # Salı
        (2, "08:30", "18:00"),  # Çarşamba
        (3, "08:30", "18:00"),  # Perşembe
        (4, "08:30", "18:00"),  # Cuma
        (5, "00:00", "00:00"),  # Cumartesi
        (6, "00:00", "00:00"),  # Pazar
    ]

    working_hours = [
        WorkingHour(
            company=instance,
            day_of_week=day,
            start_time=start,
            end_time=end,
            is_holiday=(day >= 5),
        )
        for day, start, end in default_hours
    ]

    WorkingHour.objects.bulk_create(working_hours)



# ----------------------------
# 1. Singleton guard (extra güvenlik)
# ----------------------------
@receiver(pre_save, sender=CompanyConfig)
def ensure_single_company_config(sender, instance, **kwargs):
    if not instance.pk:
        exists = CompanyConfig.objects.filter(tenant=instance.tenant).exists()
        if exists:
            raise ValidationError("Sadece bir adet firma yapılandırması oluşturulabilir.")


# ----------------------------
# 2. WorkingHour otomatik fix (duplicate / eksik gün engelleme)
# ----------------------------
@receiver(post_save, sender=CompanyConfig)
def create_default_working_hours(sender, instance, created, **kwargs):
    if not created:
        return

    existing_days = set(
        WorkingHour.objects.filter(company=instance).values_list("day_of_week", flat=True)
    )

    default_hours = []

    for day in range(7):
        if day in existing_days:
            continue

        is_weekend = day >= 5

        default_hours.append(
            WorkingHour(
                company=instance,
                day_of_week=day,
                start_time="08:30" if not is_weekend else "00:00",
                end_time="18:00" if not is_weekend else "00:00",
                is_holiday=is_weekend,
            )
        )

    if default_hours:
        WorkingHour.objects.bulk_create(default_hours)

WORKING_HOUR_FIELDS = ('start_time', 'end_time', 'is_holiday')
HOLIDAY_EXCEPTION_FIELDS = ('title', 'start_date', 'end_date', 'is_half_day', 'note')
TECHNICIAN_SCHEDULE_SCREEN = 'ProfileMyShifts'


def _technician_users(tenant):
    return [
        technician.user
        for technician in Technician.objects.filter(
            tenant=tenant,
            user__is_active=True,
        ).select_related('user')
    ]


def _send_technician_schedule_notification(tenant, title, message, related_id):
    users = _technician_users(tenant)
    if users:
        create_bulk_notification(
            users=users,
            title=title,
            message=message,
            related_id=related_id,
            related_screen=TECHNICIAN_SCHEDULE_SCREEN,
        )


@receiver(pre_save, sender=WorkingHour)
def detect_working_hour_change(sender, instance, **kwargs):
    instance._schedule_notification_changed = False
    if not instance.pk:
        return

    previous = sender.objects.filter(pk=instance.pk).values(*WORKING_HOUR_FIELDS).first()
    if previous:
        instance._schedule_notification_changed = any(
            previous[field] != getattr(instance, field)
            for field in WORKING_HOUR_FIELDS
        )


@receiver(post_save, sender=WorkingHour)
def notify_technicians_of_working_hour_change(sender, instance, created, **kwargs):
    if created or not getattr(instance, '_schedule_notification_changed', False):
        return

    tenant = instance.company.tenant
    if not tenant:
        return

    day_name = instance.get_day_of_week_display()
    if instance.is_holiday:
        title = 'Çalışma Planı Güncellendi'
        message = f"{day_name} günü tatil olarak güncellendi. Lütfen yeni çalışma planınızı kontrol edin."
    else:
        title = 'Çalışma Saatleri Güncellendi'
        message = (
            f"{day_name} günü çalışma saatleri "
            f"{instance.start_time.strftime('%H:%M')} - {instance.end_time.strftime('%H:%M')} "
            f"olarak güncellendi. Yeni planınızı kontrol etmenizi rica ederiz."
        )

    transaction.on_commit(
        lambda: _send_technician_schedule_notification(
            tenant,
            title,
            message,
            f'working-hour:{instance.pk}',
        )
    )


@receiver(pre_save, sender=HolidayException)
def detect_holiday_exception_change(sender, instance, **kwargs):
    instance._schedule_notification_changed = not bool(instance.pk)
    if not instance.pk:
        return

    previous = sender.objects.filter(pk=instance.pk).values(*HOLIDAY_EXCEPTION_FIELDS).first()
    if previous:
        instance._schedule_notification_changed = any(
            previous[field] != getattr(instance, field)
            for field in HOLIDAY_EXCEPTION_FIELDS
        )


@receiver(post_save, sender=HolidayException)
def notify_technicians_of_holiday(sender, instance, created, **kwargs):
    if not getattr(instance, '_schedule_notification_changed', created):
        return

    tenant = instance.company.tenant
    if not tenant:
        return

    title = 'Tatil Duyurusu'
    start_label = instance.start_date.strftime('%d.%m.%Y')
    end_label = (instance.end_date or instance.start_date).strftime('%d.%m.%Y')
    if instance.is_half_day:
        period = f"{start_label} tarihinde yarım gün tatil uygulanacaktır."
    elif instance.start_date == (instance.end_date or instance.start_date):
        period = f"{start_label} tarihinde tatil uygulanacaktır."
    else:
        period = f"{start_label} - {end_label} tarihleri arasında tatil uygulanacaktır."

    note = str(instance.note or '').strip()
    message = f"{instance.title}: {period}"
    if note:
        message += f"\nNot: {note}"

    transaction.on_commit(
        lambda: _send_technician_schedule_notification(
            tenant,
            title,
            message,
            f'holiday:{instance.pk}:{instance.updated_at.isoformat()}',
        )
    )
