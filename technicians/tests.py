from datetime import datetime, time

from config.models import CompanyConfig, WorkingHour
from django.test import TestCase
from django.utils import timezone
from notifications.models import Notification
from tenants.models import Tenant
from accounts.models import User

from .models import Technician, TechnicianAttendance, TechnicianShift
from .shift_reminders import (
    END_REMINDER_SCREEN,
    REMINDER_SCREEN,
    send_shift_end_reminders,
    send_shift_start_reminders,
)


class ShiftStartReminderTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Reminder Tenant', code='reminder-tenant')
        self.company = CompanyConfig.objects.create(tenant=self.tenant, name='Reminder Company')
        self.user = User.objects.create_user(
            email='reminder-tech@example.com',
            password='pass123',
            tenant=self.tenant,
            user_type='technician',
        )
        self.technician = Technician.objects.create(user=self.user, tenant=self.tenant)
        self.today = timezone.localdate()
        WorkingHour.objects.update_or_create(
            company=self.company,
            day_of_week=self.today.weekday(),
            defaults={
                'tenant': self.tenant,
                'start_time': time(8, 30),
                'end_time': time(18, 0),
                'is_holiday': False,
            },
        )
        self.reminder_time = timezone.make_aware(
            datetime.combine(self.today, time(9, 0)),
            timezone.get_current_timezone(),
        )

    def test_reminds_once_when_shift_has_not_started(self):
        result = send_shift_start_reminders(now=self.reminder_time)

        self.assertEqual(result['sent'], 1)
        self.assertEqual(Notification.objects.filter(related_screen=REMINDER_SCREEN).count(), 1)

        repeated_result = send_shift_start_reminders(now=self.reminder_time)

        self.assertEqual(repeated_result['sent'], 0)

    def test_skips_technician_on_leave_or_with_open_shift(self):
        TechnicianAttendance.objects.create(
            tenant=self.tenant,
            technician=self.technician,
            date=self.today,
            status=TechnicianAttendance.STATUS_LEAVE,
        )

        leave_result = send_shift_start_reminders(now=self.reminder_time)
        self.assertEqual(leave_result['sent'], 0)

        TechnicianAttendance.objects.filter(technician=self.technician, date=self.today).delete()
        TechnicianShift.objects.create(
            tenant=self.tenant,
            technician=self.user,
            date=self.today,
            start_time=self.reminder_time,
        )

        open_shift_result = send_shift_start_reminders(now=self.reminder_time)
        self.assertEqual(open_shift_result['sent'], 0)


    def test_reminds_once_when_shift_has_not_ended(self):
        end_reminder_time = timezone.make_aware(
            datetime.combine(self.today, time(18, 30)),
            timezone.get_current_timezone(),
        )
        TechnicianShift.objects.create(
            tenant=self.tenant,
            technician=self.user,
            date=self.today,
            start_time=self.reminder_time,
        )

        result = send_shift_end_reminders(now=end_reminder_time)

        self.assertEqual(result['sent'], 1)
        self.assertEqual(Notification.objects.filter(related_screen=END_REMINDER_SCREEN).count(), 1)

        repeated_result = send_shift_end_reminders(now=end_reminder_time)
        self.assertEqual(repeated_result['sent'], 0)
