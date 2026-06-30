from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from config.models import CompanyConfig
from customers.models import Customer
from customers.serializers import CustomerSerializer
from tenants.models import Tenant


class CustomerSerializerTests(TestCase):
    def test_serializer_exposes_expected_fields(self):
        tenant = Tenant.objects.create(name="Tenant A", code="cust-ser")
        customer = Customer.objects.create(
            tenant=tenant,
            full_name="Ada Lovelace",
            phone_number="5551234567",
            email="ada@example.com",
        )

        data = CustomerSerializer(customer).data

        self.assertEqual(data["full_name"], "Ada Lovelace")
        self.assertEqual(data["phone_number"], "5551234567")
        self.assertEqual(data["email"], "ada@example.com")
        self.assertEqual(data["tenant"], str(tenant.pk))


class CustomerApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(name="Tenant A", code="cust-api-a")
        self.other_tenant = Tenant.objects.create(name="Tenant B", code="cust-api-b")
        CompanyConfig.objects.create(tenant=self.tenant, name="Firma A")
        CompanyConfig.objects.create(tenant=self.other_tenant, name="Firma B")
        self.user = User.objects.create_user(
            email="customer-admin@example.com",
            password="secret123",
            tenant=self.tenant,
            user_type="admin",
            approval_status="approved",
            is_active=True,
        )
        self.client.force_authenticate(user=self.user)
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            full_name="Grace Hopper",
            phone_number="5550000001",
            email="grace@example.com",
        )
        Customer.objects.create(
            tenant=self.other_tenant,
            full_name="Alan Turing",
            phone_number="5550000002",
            email="alan@example.com",
        )

    def test_list_returns_only_current_tenant_customers(self):
        response = self.client.get("/api/customers/customers/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["full_name"], "Grace Hopper")

    def test_create_sets_tenant_from_authenticated_user(self):
        response = self.client.post(
            "/api/customers/customers/",
            {
                "full_name": "Katherine Johnson",
                "phone_number": "5550000003",
                "email": "katherine@example.com",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        created = Customer.objects.get(email="katherine@example.com")
        self.assertEqual(created.tenant, self.tenant)

    def test_delete_soft_deletes_customer(self):
        response = self.client.delete(f"/api/customers/customers/{self.customer.pk}/")

        self.assertEqual(response.status_code, 204)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_deleted)

    def test_list_hides_soft_deleted_customers(self):
        self.customer.is_deleted = True
        self.customer.save(update_fields=["is_deleted"])

        response = self.client.get("/api/customers/customers/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_list_can_include_deleted_customers(self):
        self.customer.is_deleted = True
        self.customer.save(update_fields=["is_deleted"])

        response = self.client.get("/api/customers/customers/?include_deleted=true")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertTrue(response.data[0]["is_deleted"])

    def test_restore_endpoint_reactivates_soft_deleted_customer(self):
        self.customer.is_deleted = True
        self.customer.save(update_fields=["is_deleted"])

        response = self.client.post(
            f"/api/customers/customers/{self.customer.pk}/restore/",
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_deleted)

    def test_restore_endpoint_rejects_active_customer(self):
        response = self.client.post(
            f"/api/customers/customers/{self.customer.pk}/restore/",
            format="json",
        )

        self.assertEqual(response.status_code, 400)
