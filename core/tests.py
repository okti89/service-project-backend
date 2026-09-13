from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from customers.models import Customer
from products.models import Product
from services.models import Service
from technicians.models import Technician
from tenants.models import Tenant


class GlobalSearchTenantIsolationTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Search A", code="search-a")
        self.other_tenant = Tenant.objects.create(name="Search B", code="search-b")
        self.admin = User.objects.create_user(
            email="search-admin@example.com",
            password="pass123",
            tenant=self.tenant,
            user_type="admin",
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            full_name="Shared Search Own",
            phone_number="05550000001",
        )
        self.other_customer = Customer.objects.create(
            tenant=self.other_tenant,
            full_name="Shared Search Other",
            phone_number="05550000002",
        )
        self.service = Service.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            customer_full_name=self.customer.full_name,
            fault_description="shared query own",
            scheduled_date=timezone.now() + timedelta(days=1),
        )
        Service.objects.create(
            tenant=self.other_tenant,
            customer=self.other_customer,
            customer_full_name=self.other_customer.full_name,
            fault_description="shared query other",
            scheduled_date=timezone.now() + timedelta(days=1),
        )
        other_user = User.objects.create_user(
            email="shared-other@example.com",
            password="pass123",
            tenant=self.other_tenant,
        )
        Technician.objects.create(tenant=self.other_tenant, user=other_user)
        Product.objects.create(tenant=self.other_tenant, name="Shared Other Product")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_search_ignores_forged_tenant_header_and_returns_only_user_tenant(self):
        response = self.client.get(
            "/api/global-search/",
            {"q": "Shared"},
            HTTP_X_TENANT_CODE=self.other_tenant.code,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["customers"]], [str(self.customer.id)])
        self.assertEqual([item["id"] for item in response.data["services"]], [str(self.service.id)])
        self.assertEqual(response.data["technicians"], [])
        self.assertEqual(response.data["products"], [])
