from datetime import datetime, time, timedelta

from config.models import HolidayException, WorkingHour
from django.db.models import Q
from django.utils import timezone
from notifications.models import Notification
from notifications.services import create_notification

from .models import Technician, TechnicianAttendance, TechnicianShift


REMINDER_SCREEN = 'ShiftStartReminder'
REMINDER_TITLE = 'Mesai Başlangıç Hatırlatması'
DEFAULT_START_TIME = time(hour=8, minute=30)
DEFAULT_END_TIME = time(hour=18, minute=0)
NON_WORKING_ATTENDANCE_STATUSES = {
    TechnicianAttendance.STATUS_LEAVE,
    TechnicianAttendance.STATUS_SICK,
    TechnicianAttendance.STATUS_OFFDAY,
    TechnicianAttendance.STATUS_ABSENT,
}


def _reminder_exists(user, work_date):
    return Notification.objects.filter(
        user=user,
        related_screen=REMINDER_SCREEN,
        related_id=work_date.isoformat(),
    ).exists()


def _work_schedule_by_tenant(tenant_ids, weekday):
    schedules = {
        tenant_id: (DEFAULT_START_TIME, DEFAULT_END_TIME)
        for tenant_id in tenant_ids
    }
    for working_hour in WorkingHour.objects.filter(
        company__tenant_id__in=tenant_ids,
        day_of_week=weekday,
    ).select_related('company'):
        if working_hour.is_holiday:
            schedules[working_hour.company.tenant_id] = None
        else:
            schedules[working_hour.company.tenant_id] = (
                working_hour.start_time,
                working_hour.end_time,
            )
    return schedules


def send_shift_start_reminders(now=None, grace_minutes=10, force=False):
    """Remind working technicians once after their workday starts without a shift."""
    if grace_minutes < 0:
        raise ValueError('grace_minutes must be zero or greater.')

    now = timezone.localtime(now or timezone.now())
    work_date = now.date()
    technicians = list(
        Technician.objects.filter(
            user__is_active=True,
            tenant__isnull=False,
        ).select_related('user', 'tenant')
    )
    if not technicians:
        return {'sent': 0, 'skipped': 0, 'date': work_date}

    tenant_ids = {technician.tenant_id for technician in technicians}
    schedules = _work_schedule_by_tenant(tenant_ids, work_date.weekday())
    holiday_tenant_ids = set(
        HolidayException.objects.filter(
            company__tenant_id__in=tenant_ids,
            start_date__lte=work_date,
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=work_date)
        ).values_list('company__tenant_id', flat=True)
    )
    attendance_by_technician = {
        row.technician_id: row.status
        for row in TechnicianAttendance.objects.filter(
            technician_id__in=[technician.id for technician in technicians],
            date=work_date,
        )
    }
    users_with_open_shift = set(
        TechnicianShift.objects.filter(
            technician_id__in=[technician.user_id for technician in technicians],
            end_time__isnull=True,
        ).values_list('technician_id', flat=True)
    )

    sent_count = 0
    skipped_count = 0
    for technician in technicians:
        user = technician.user
        if technician.tenant_id in holiday_tenant_ids:
            skipped_count += 1
            continue

        schedule = schedules.get(technician.tenant_id)
        if not schedule:
            skipped_count += 1
            continue

        attendance_status = attendance_by_technician.get(technician.id)
        if attendance_status in NON_WORKING_ATTENDANCE_STATUSES:
            skipped_count += 1
            continue

        if user.id in users_with_open_shift:
            skipped_count += 1
            continue

        start_time, end_time = schedule
        if now.time() > end_time:
            skipped_count += 1
            continue

        scheduled_start = timezone.make_aware(
            datetime.combine(work_date, start_time),
            timezone.get_current_timezone(),
        )
        if now < scheduled_start + timedelta(minutes=grace_minutes):
            skipped_count += 1
            continue

        if not force and _reminder_exists(user, work_date):
            skipped_count += 1
            continue

        create_notification(
            user=user,
            title=REMINDER_TITLE,
            message=(
                f"Günaydın {user.get_full_name()}. "
                f"Mesai başlangıç saatiniz {start_time.strftime('%H:%M')} "
                f"olarak planlandı. Henüz mesai başlangıç kaydınız görünmüyor. "
                f"Hazır olduğunuzda uygulamadan Mesaiyi Başlat seçeneğini kullanabilirsiniz."
            ),
            related_id=work_date.isoformat(),
            related_screen=REMINDER_SCREEN,
        )
        sent_count += 1

    return {'sent': sent_count, 'skipped': skipped_count, 'date': work_date}


END_REMINDER_SCREEN = 'ShiftEndReminder'
END_REMINDER_TITLE = 'Mesai Bitiş Hatırlatması'


def send_shift_end_reminders(now=None, grace_minutes=15, force=False):
    """Remind technicians once when today's open shift continues past work hours."""
    if grace_minutes < 0:
        raise ValueError('grace_minutes must be zero or greater.')

    now = timezone.localtime(now or timezone.now())
    work_date = now.date()
    open_shifts = list(
        TechnicianShift.objects.filter(
            date=work_date,
            end_time__isnull=True,
            technician__is_active=True,
            technician__tenant__isnull=False,
        ).select_related('technician', 'technician__tenant')
    )
    if not open_shifts:
        return {'sent': 0, 'skipped': 0, 'date': work_date}

    tenant_ids = {shift.technician.tenant_id for shift in open_shifts}
    schedules = _work_schedule_by_tenant(tenant_ids, work_date.weekday())
    sent_count = 0
    skipped_count = 0

    for shift in open_shifts:
        user = shift.technician
        schedule = schedules.get(user.tenant_id)
        if not schedule:
            skipped_count += 1
            continue

        _, end_time = schedule
        scheduled_end = timezone.make_aware(
            datetime.combine(work_date, end_time),
            timezone.get_current_timezone(),
        )
        if now < scheduled_end + timedelta(minutes=grace_minutes):
            skipped_count += 1
            continue

        already_sent = Notification.objects.filter(
            user=user,
            related_screen=END_REMINDER_SCREEN,
            related_id=work_date.isoformat(),
        ).exists()
        if already_sent and not force:
            skipped_count += 1
            continue

        create_notification(
            user=user,
            title=END_REMINDER_TITLE,
            message=(
                f"Merhaba {user.get_full_name()}. "
                f"Mesai bitiş saatiniz {end_time.strftime('%H:%M')} "
                f"olarak planlandı ancak mesai kaydınız hâlâ açık görünüyor. "
                f"Gün sonu kaydınızı tamamlamak için Mesaiyi Bitir seçeneğini kullanabilirsiniz."
            ),
            related_id=work_date.isoformat(),
            related_screen=END_REMINDER_SCREEN,
        )
        sent_count += 1

    return {'sent': sent_count, 'skipped': skipped_count, 'date': work_date}
