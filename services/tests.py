from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from django.test import RequestFactory, TestCase
from django.utils import timezone

from accounts.models import User
from customers.models import Customer
from tenants.models import Tenant
from technicians.models import Technician

from .models import Service, WarrantyCertificate
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
