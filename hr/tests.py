from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from accounts.models import User
from hr.models import Payroll, PayrollTemplate
from hr.serializers import PayrollSerializer
from hr.views import TechnicianPayrollPDFView
from technicians.models import Technician
from tenants.models import Tenant


class HRModelCompatibilityTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Tenant A", code="tenant-a")
        self.other_tenant = Tenant.objects.create(name="Tenant B", code="tenant-b")

        self.user = User.objects.create_user(
            email="tech@example.com",
            password="test123",
            tenant=self.tenant,
            user_type="technician",
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
            password="test123",
            tenant=self.other_tenant,
            user_type="technician",
        )

        self.technician = Technician.objects.create(user=self.user, tenant=self.tenant)
        self.other_technician = Technician.objects.create(
            user=self.other_user,
            tenant=self.other_tenant,
        )

    def test_payroll_template_model_is_available(self):
        template = PayrollTemplate.objects.create(
            tenant=self.tenant,
            name="Yemek Karti",
            type="addition",
            default_amount=Decimal("750.00"),
            is_active=True,
        )

        self.assertEqual(template.tenant, self.tenant)
        self.assertEqual(template.type, "addition")

    def test_is_paid_property_tracks_status(self):
        payroll = Payroll(
            tenant=self.tenant,
            technician=self.technician,
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 31),
            base_salary=Decimal("1000.00"),
        )

        self.assertFalse(payroll.is_paid)

        payroll.is_paid = True
        self.assertEqual(payroll.status, "paid")
        self.assertTrue(payroll.is_paid)

        payroll.status = "cancelled"
        payroll.is_paid = False
        self.assertEqual(payroll.status, "cancelled")

    def test_payroll_serializer_forces_request_tenant(self):
        request = APIRequestFactory().post("/api/hr/payrolls/")
        request.user = User.objects.create_user(
            email="manager@example.com",
            password="test123",
            tenant=self.tenant,
            user_type="admin",
        )

        serializer = PayrollSerializer(
            data={
                "tenant": str(self.other_tenant.id),
                "technician": str(self.technician.id),
                "period_start": "2026-05-01",
                "period_end": "2026-05-31",
                "base_salary": "25000.00",
                "status": "draft",
            },
            context={"request": request},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        payroll = serializer.save()

        self.assertEqual(payroll.tenant, self.tenant)

    def test_technician_pdf_view_blocks_cross_tenant_payroll(self):
        payroll = Payroll.objects.create(
            tenant=self.other_tenant,
            technician=self.technician,
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 31),
            base_salary=Decimal("1000.00"),
        )

        request = APIRequestFactory().get(f"/api/hr/me/payrolls/{payroll.id}/pdf/")
        request.user = self.user

        response = TechnicianPayrollPDFView.as_view()(request, pk=payroll.id)

        self.assertEqual(response.status_code, 404)

    def test_payroll_serializer_uses_email_when_name_surname_missing(self):
        payroll = Payroll.objects.create(
            tenant=self.tenant,
            technician=self.technician,
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            base_salary=Decimal("1000.00"),
        )
        self.user.first_name = ""
        self.user.last_name = ""
        self.user.save(update_fields=["first_name", "last_name"])

        data = PayrollSerializer(payroll).data

        self.assertEqual(data["technician_name"], "tech@example.com")
        self.assertEqual(data["technician_email"], "tech@example.com")
