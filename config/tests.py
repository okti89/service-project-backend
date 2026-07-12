from datetime import time, timedelta

from accounts.models import User
from config.models import CompanyConfig, HolidayException, WorkingHour
from django.test import TestCase
from django.utils import timezone
from notifications.models import Notification
from tenants.models import Tenant
from technicians.models import Technician


class ScheduleNotificationSignalTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Schedule Tenant', code='schedule-tenant')
        self.company = CompanyConfig.objects.create(tenant=self.tenant, name='Schedule Company')
        self.user = User.objects.create_user(
            email='schedule-tech@example.com',
            password='pass123',
            tenant=self.tenant,
            user_type='technician',
        )
        Technician.objects.create(user=self.user, tenant=self.tenant)

    def test_working_hour_change_notifies_technicians(self):
        working_hour = WorkingHour.objects.get(company=self.company, day_of_week=0)
        with self.captureOnCommitCallbacks(execute=True):
            working_hour.start_time = time(9, 0)
            working_hour.end_time = time(17, 30)
            working_hour.save()

        notification = Notification.objects.get(user=self.user)
        self.assertIn('09:00 - 17:30', notification.message)
        self.assertEqual(notification.related_screen, 'ProfileMyShifts')

    def test_holiday_announcement_notifies_technicians(self):
        holiday_date = timezone.localdate() + timedelta(days=7)
        with self.captureOnCommitCallbacks(execute=True):
            HolidayException.objects.create(
                tenant=self.tenant,
                company=self.company,
                title='National Holiday',
                start_date=holiday_date,
            )

        notification = Notification.objects.get(user=self.user)
        self.assertIn('National Holiday', notification.message)
        self.assertEqual(notification.related_screen, 'ProfileMyShifts')
