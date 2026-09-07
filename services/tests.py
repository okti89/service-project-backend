from datetime import datetime, time, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from customers.models import Customer
from tenants.models import Tenant
from technicians.models import Technician, TechnicianPermissions
from notifications.models import Notification

from .daily_summary import send_daily_service_summaries
from .operational_alerts import send_operational_alerts

from .models import Service, ServiceOperations, ServicePayment, WarrantyCertificate
from .serializers import PublicServiceSerializer, WarrantyCertificateSerializer
from .views import (
    _build_public_service_tracking_url,
    _build_service_pdf_filename,
    _build_service_status_whatsapp_url,
    resolve_public_service_token,
)


class ServiceSerializerRegressionTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Tenant", code="tenant-services")
        self.user = User.objects.create_user(
            email="techsvc@example.com",
            password="pass123",
            tenant=self.tenant,
            user_type="technician",
        )
        self.technician = Technician.objects.create(user=self.user, tenant=self.tenant)
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            full_name="Test Customer",
            phone_number="5551112233",
        )
        self.factory = RequestFactory()
        self.service = Service.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            customer_full_name=self.customer.full_name,
            customer_phone=self.customer.phone_number,
            fault_description="No heat",
            technician=self.technician,
            scheduled_date=timezone.now() + timedelta(days=1),
        )

    def test_public_service_serializer_uses_existing_fields_only(self):
        data = PublicServiceSerializer(self.service).data

        self.assertEqual(data["receipt_number"], self.service.receipt_number)
        self.assertIn("status_name", data)
        self.assertNotIn("technician_status", data)
        self.assertNotIn("technician_status_updated_at", data)

    def test_whatsapp_status_message_uses_status_and_tracking_link(self):
        request = self.factory.post(
            "/api/services/admin-services/",
            HTTP_ORIGIN="https://panel.example.com",
        )

        whatsapp_url = _build_service_status_whatsapp_url(
            self.service,
            new_status="postponed",
            request=request,
            status_changed=True,
        )
        message = parse_qs(urlparse(whatsapp_url).query)["text"][0]

        self.assertIn("Servis Durumunuz Ertelendi olarak değiştirildi.", message)
        self.assertIn(f"Takip etmek için: https://panel.example.com/service-tracking/{self.service.id}/", message)
        self.assertNotIn("Merhaba", message)
        self.assertNotIn("Fis No", message)
        self.assertNotIn("Yeni Durum", message)
        self.assertNotIn("Randevu", message)

    def test_whatsapp_schedule_message_uses_appointment_and_tracking_link(self):
        request = self.factory.post(
            "/api/services/admin-services/",
            HTTP_ORIGIN="https://panel.example.com",
        )

        whatsapp_url = _build_service_status_whatsapp_url(
            self.service,
            request=request,
            schedule_changed=True,
            scheduled_date=self.service.scheduled_date,
        )
        message = parse_qs(urlparse(whatsapp_url).query)["text"][0]

        self.assertIn("Servis randevunuz", message)
        self.assertIn(f"Takip etmek için: https://panel.example.com/service-tracking/{self.service.id}/", message)

    def test_public_tracking_link_contains_resolvable_access_token(self):
        request = self.factory.get(
            "/api/services/admin-services/",
            HTTP_ORIGIN="https://panel.example.com",
        )

        tracking_url = _build_public_service_tracking_url(self.service, request=request)
        token = parse_qs(urlparse(tracking_url).query)["access_token"][0]

        self.assertTrue(tracking_url.startswith(f"https://panel.example.com/service-tracking/{self.service.id}/"))
        self.assertEqual(resolve_public_service_token(token), str(self.service.id))

    def test_pdf_filename_includes_customer_and_receipt(self):
        filename = _build_service_pdf_filename(self.service)

        self.assertTrue(filename.endswith('.pdf'))
        self.assertIn(self.service.receipt_number, filename)
        self.assertIn('Test_Customer', filename)

    def test_warranty_certificate_serializer_uses_existing_fields_only(self):
        certificate = WarrantyCertificate.objects.create(
            tenant=self.tenant,
            service=self.service,
            warranty_months=12,
            start_date=timezone.localdate(),
        )

        data = WarrantyCertificateSerializer(certificate).data

        self.assertEqual(data["certificate_no"], certificate.certificate_no)
        self.assertEqual(Decimal(str(data["warranty_months"])), Decimal("12"))
        self.assertNotIn("terms_snapshot", data)


class WeeklyScheduledServiceSummaryTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Weekly Tenant", code="weekly-tenant")
        self.other_tenant = Tenant.objects.create(name="Other Tenant", code="other-weekly-tenant")
        self.admin = User.objects.create_user(
            email="weekly-admin@example.com",
            password="pass123",
            tenant=self.tenant,
            user_type="admin",
        )
        self.technician_user = User.objects.create_user(
            email="weekly-tech@example.com",
            password="pass123",
            tenant=self.tenant,
            user_type="technician",
        )
        self.technician = Technician.objects.create(
            user=self.technician_user,
            tenant=self.tenant,
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            full_name="Weekly Customer",
            phone_number="5550001122",
        )
        self.other_customer = Customer.objects.create(
            tenant=self.other_tenant,
            full_name="Other Customer",
            phone_number="5550003344",
        )
        self.client = APIClient()

    @staticmethod
    def _at_noon(day):
        return timezone.make_aware(
            datetime.combine(day, time(hour=12)),
            timezone.get_current_timezone(),
        )

    def _create_service(self, tenant, customer, scheduled_day):
        return Service.objects.create(
            tenant=tenant,
            customer=customer,
            customer_full_name=customer.full_name,
            customer_phone=customer.phone_number,
            scheduled_date=self._at_noon(scheduled_day),
        )

    def test_returns_current_week_counts_grouped_by_appointment_day_for_tenant(self):
        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())
        self._create_service(self.tenant, self.customer, monday)
        self._create_service(self.tenant, self.customer, monday)
        self._create_service(self.tenant, self.customer, monday + timedelta(days=2))
        self._create_service(self.tenant, self.customer, monday - timedelta(days=1))
        self._create_service(self.other_tenant, self.other_customer, monday)

        self.client.force_authenticate(self.admin)
        response = self.client.get(reverse("weekly-scheduled-service-summary"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["week_start"], monday.isoformat())
        self.assertEqual(response.data["week_end"], (monday + timedelta(days=6)).isoformat())
        self.assertEqual(response.data["total"], 3)
        self.assertEqual([day["label"] for day in response.data["days"]], ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"])
        self.assertEqual([day["count"] for day in response.data["days"]], [2, 0, 1, 0, 0, 0, 0])

    def test_rejects_technician_without_service_management_permission(self):
        self.client.force_authenticate(self.technician_user)

        response = self.client.get(reverse("weekly-scheduled-service-summary"))

        self.assertEqual(response.status_code, 403)

    def test_allows_technician_with_service_management_permission(self):
        TechnicianPermissions.objects.update_or_create(
            technician=self.technician,
            defaults={
                "tenant": self.tenant,
                "can_manage_services": True,
            },
        )
        self.client.force_authenticate(self.technician_user)

        response = self.client.get(reverse("weekly-scheduled-service-summary"))

        self.assertEqual(response.status_code, 200)


class DailyServiceSummaryTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Summary Tenant', code='summary-tenant')
        self.manager = User.objects.create_user(
            email='manager-summary@example.com',
            password='pass123',
            tenant=self.tenant,
            user_type='admin',
        )
        self.technician_user = User.objects.create_user(
            email='technician-summary@example.com',
            password='pass123',
            tenant=self.tenant,
            user_type='technician',
        )
        self.technician = Technician.objects.create(user=self.technician_user, tenant=self.tenant)
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            full_name='Summary Customer',
            phone_number='5553334455',
        )
        Service.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            customer_full_name=self.customer.full_name,
            customer_phone=self.customer.phone_number,
            technician=self.technician,
            scheduled_date=timezone.now(),
        )

    def test_sends_manager_and_technician_summaries_once_per_day(self):
        summary_date = timezone.localdate()

        result = send_daily_service_summaries(summary_date=summary_date)

        self.assertEqual(result['sent'], 2)
        self.assertEqual(Notification.objects.filter(related_screen='DailyServiceSummary').count(), 2)
        self.assertIn('1', Notification.objects.get(user=self.manager).message)
        self.assertIn('1', Notification.objects.get(user=self.technician_user).message)

        repeated_result = send_daily_service_summaries(summary_date=summary_date)

        self.assertEqual(repeated_result['sent'], 0)
        self.assertEqual(repeated_result['skipped'], 2)


class OperationalAlertTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Alerts Tenant', code='alerts-tenant')
        self.manager = User.objects.create_user(
            email='alerts-manager@example.com',
            password='pass123',
            tenant=self.tenant,
            user_type='admin',
        )
        self.technician_user = User.objects.create_user(
            email='alerts-tech@example.com',
            password='pass123',
            tenant=self.tenant,
            user_type='technician',
        )
        self.technician = Technician.objects.create(user=self.technician_user, tenant=self.tenant)
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            full_name='Alerts Customer',
            phone_number='5557778899',
        )
        self.now = timezone.now()

    def create_service(self, **kwargs):
        defaults = {
            'tenant': self.tenant,
            'customer': self.customer,
            'customer_full_name': self.customer.full_name,
            'customer_phone': self.customer.phone_number,
            'customer_address': 'Test Address',
            'scheduled_date': self.now,
        }
        defaults.update(kwargs)
        return Service.objects.create(**defaults)

    def test_sends_unassigned_overdue_and_receivable_alerts(self):
        self.create_service(scheduled_date=self.now + timedelta(hours=2))
        self.create_service(
            technician=self.technician,
            scheduled_date=self.now - timedelta(hours=2),
        )
        completed_service = self.create_service(
            technician=self.technician,
            scheduled_date=self.now - timedelta(days=1),
        )
        completed_service.service_status = 'completed'
        completed_service.save()
        ServiceOperations.objects.create(
            service=completed_service,
            name='Test Operation',
            quantity=1,
            unit_price=Decimal('100.00'),
        )
        ServicePayment.objects.create(service=completed_service, amount=Decimal('40.00'))

        result = send_operational_alerts(now=self.now)

        self.assertEqual(result['unassigned'], 1)
        self.assertEqual(result['overdue'], 2)
        self.assertEqual(result['receivable'], 1)
        self.assertEqual(result['total_sent'], 4)

        repeated_result = send_operational_alerts(now=self.now)
        self.assertEqual(repeated_result['total_sent'], 0)
