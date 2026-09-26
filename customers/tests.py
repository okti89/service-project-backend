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
        self.assertEqual(data["phone_number"], "05551234567")
        self.assertEqual(data["email"], "ada@example.com")
        self.assertEqual(data["tenant"], str(tenant.pk))


class CustomerApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(name="Tenant A", code="cust-api-a")
        self.other_tenant = Tenant.objects.create(name="Tenant B", code="cust-api-b")
        CompanyConfig.objects.filter(tenant=self.tenant).update(name="Firma A")
        CompanyConfig.objects.filter(tenant=self.other_tenant).update(name="Firma B")
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


class CustomerPaginationTests(TestCase):
    def setUp(self):
        CustomerApiTests.setUp(self)
        Customer.objects.bulk_create([
            Customer(
                tenant=self.tenant,
                full_name=f'Customer {index:03d}',
                phone_number=f'0555000{index:04d}',
                is_deleted=index >= 110,
            ) for index in range(120)
        ])

    def get_page(self, **params):
        response = self.client.get('/api/customers/customers/', {'page': 1, 'status': 'all', **params})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_default_page_size_and_summary_cover_all_records(self):
        data = self.get_page()
        self.assertEqual(len(data['results']), 50)
        self.assertEqual(data['count'], 121)
        self.assertEqual(data['summary'], {'total': 121, 'active': 111, 'inactive': 10})
        self.assertIsNotNone(data['next'])

    def test_pages_are_ordered_and_have_no_duplicate_records(self):
        pages = [self.get_page(page=number) for number in (1, 2, 3)]
        rows = [row for page in pages for row in page['results']]
        self.assertEqual(len(rows), 121)
        self.assertEqual(len({row['id'] for row in rows}), 121)
        self.assertEqual([row['full_name'] for row in rows], sorted(row['full_name'] for row in rows))
        self.assertIsNone(pages[-1]['next'])

    def test_search_finds_records_not_in_the_first_page(self):
        data = self.get_page(search='Customer 119')
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['full_name'], 'Customer 119')
        self.assertEqual(data['summary'], {'total': 1, 'active': 0, 'inactive': 1})

    def test_digits_in_customer_names_do_not_trigger_phone_search(self):
        self.assertEqual(self.get_page(search='Customer 00')['count'], 10)

    def test_status_filter_does_not_reduce_summary_to_one_page(self):
        active = self.get_page(status='active')
        inactive = self.get_page(status='inactive')
        self.assertEqual(active['count'], 111)
        self.assertTrue(all(not row['is_deleted'] for row in active['results']))
        self.assertEqual(inactive['count'], 10)
        self.assertTrue(all(row['is_deleted'] for row in inactive['results']))
        self.assertEqual(active['summary'], inactive['summary'])

    def test_page_size_is_bounded(self):
        self.assertEqual(len(self.get_page(page_size=1000)['results']), 100)
        self.assertEqual(len(self.get_page(page_size=20)['results']), 20)

    def test_paginated_results_never_include_other_tenants(self):
        data = self.get_page(search='Alan Turing')
        self.assertEqual(data['count'], 0)
        self.assertEqual(data['results'], [])
        self.assertEqual(data['summary']['total'], 0)

    def test_phone_search_accepts_formatted_international_number(self):
        data = self.get_page(search='+90 555 000 00 01')
        self.assertTrue(any(row['id'] == str(self.customer.id) for row in data['results']))

    def test_note_and_email_are_searched_on_the_server(self):
        self.customer.note = 'Searchable repair note'
        self.customer.save(update_fields=['note'])
        for search in ('repair note', 'grace@example.com'):
            with self.subTest(search=search):
                data = self.get_page(search=search)
                self.assertEqual(data['count'], 1)
                self.assertEqual(data['results'][0]['id'], str(self.customer.id))

    def test_legacy_mobile_response_remains_an_unpaginated_list(self):
        response = self.client.get('/api/customers/customer-list/?status=all')
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 111)
