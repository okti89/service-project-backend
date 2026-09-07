from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from customers.models import Customer
from products.models import Product, StockMovement
from services.models import Service, ServiceOperations
from tenants.models import Tenant

from .models import Quote


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class QuoteAPITests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Teklif Firmasi", code="teklif-firmasi")
        self.other_tenant = Tenant.objects.create(name="Diger Firma", code="diger-firma")
        self.user = User.objects.create_user(
            email="admin-quotes@example.com",
            password="pass123",
            tenant=self.tenant,
            user_type="admin",
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            full_name="Ahmet Yilmaz",
            phone_number="05551112233",
            email="ahmet@example.com",
            address="Test adresi",
        )
        self.other_customer = Customer.objects.create(
            tenant=self.other_tenant,
            full_name="Diger Musteri",
        )
        self.product = Product.objects.create(
            tenant=self.tenant,
            name="Uc Yollu Vana",
            price=Decimal("2300.00"),
            stock_quantity=10,
        )
        self.other_product = Product.objects.create(
            tenant=self.other_tenant,
            name="Diger Urun",
            price=Decimal("100.00"),
            stock_quantity=5,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def payload(self):
        return {
            "customer": str(self.customer.id),
            "note": "Kombi bakim teklifi",
            "valid_until": (timezone.localdate() + timedelta(days=7)).isoformat(),
            "items": [
                {
                    "name": "Yillik bakim",
                    "quantity": 1,
                    "unit_price": "1500.00",
                },
                {
                    "product": str(self.product.id),
                    "quantity": 2,
                },
            ],
        }

    def create_quote(self):
        response = self.client.post("/api/quotes/", self.payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response, Quote.objects.get(pk=response.data["id"])

    def test_create_quote_calculates_total_without_touching_stock(self):
        response, quote = self.create_quote()

        self.product.refresh_from_db()
        self.assertEqual(response.data["total_price"], "6100.00")
        self.assertEqual(quote.items.count(), 2)
        self.assertEqual(self.product.stock_quantity, 10)
        self.assertFalse(StockMovement.objects.exists())

    def test_foreign_tenant_customer_is_rejected(self):
        payload = self.payload()
        payload["customer"] = str(self.other_customer.id)

        response = self.client.post("/api/quotes/", payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("customer", response.data)

    def test_foreign_tenant_product_is_rejected(self):
        payload = self.payload()
        payload["items"] = [{"product": str(self.other_product.id), "quantity": 1}]

        response = self.client.post("/api/quotes/", payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("items", response.data)

    def test_other_tenant_cannot_read_or_convert_quote(self):
        _, quote = self.create_quote()
        other_user = User.objects.create_user(
            email="other-admin@example.com",
            password="pass123",
            tenant=self.other_tenant,
            user_type="admin",
        )
        self.client.force_authenticate(other_user)

        detail_response = self.client.get(f"/api/quotes/{quote.id}/")
        convert_response = self.client.post(
            f"/api/quotes/{quote.id}/convert-to-service/",
            {"scheduled_date": (timezone.now() + timedelta(days=1)).isoformat()},
            format="json",
        )

        self.assertEqual(detail_response.status_code, 404)
        self.assertEqual(convert_response.status_code, 404)

    def test_update_replaces_items_and_recalculates_total(self):
        _, quote = self.create_quote()

        response = self.client.patch(
            f"/api/quotes/{quote.id}/",
            {
                "note": "Guncel teklif",
                "items": [
                    {"name": "Tek işlem", "quantity": 3, "unit_price": "100.00"}
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["total_price"], "300.00")
        self.assertEqual(quote.items.count(), 1)

    def test_pdf_endpoint_returns_pdf(self):
        _, quote = self.create_quote()

        response = self.client.get(f"/api/quotes/{quote.id}/pdf/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_send_email_attaches_pdf_and_marks_quote_sent(self):
        _, quote = self.create_quote()

        response = self.client.post(f"/api/quotes/{quote.id}/send-email/", {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        quote.refresh_from_db()
        self.assertIsNotNone(quote.sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.customer.email])
        self.assertEqual(mail.outbox[0].attachments[0][2], "application/pdf")

    def test_send_email_rejects_invalid_override_address(self):
        _, quote = self.create_quote()

        response = self.client.post(
            f"/api/quotes/{quote.id}/send-email/",
            {"email": "gecersiz-adres"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_convert_to_service_creates_service_items_and_stock_movement(self):
        _, quote = self.create_quote()

        response = self.client.post(
            f"/api/quotes/{quote.id}/convert-to-service/",
            {"scheduled_date": (timezone.now() + timedelta(days=1)).isoformat()},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        quote.refresh_from_db()
        self.product.refresh_from_db()
        self.assertIsNotNone(quote.converted_service_id)
        self.assertTrue(Service.objects.filter(pk=quote.converted_service_id).exists())
        self.assertEqual(ServiceOperations.objects.filter(service=quote.converted_service).count(), 2)
        self.assertEqual(self.product.stock_quantity, 8)
        self.assertEqual(StockMovement.objects.filter(product=self.product, movement_type="out").count(), 1)

    def test_converted_quote_cannot_be_changed_or_converted_twice(self):
        _, quote = self.create_quote()
        conversion_payload = {
            "scheduled_date": (timezone.now() + timedelta(days=1)).isoformat()
        }
        first = self.client.post(
            f"/api/quotes/{quote.id}/convert-to-service/",
            conversion_payload,
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)

        patch_response = self.client.patch(
            f"/api/quotes/{quote.id}/",
            {"note": "Degistirilemez"},
            format="json",
        )
        second = self.client.post(
            f"/api/quotes/{quote.id}/convert-to-service/",
            conversion_payload,
            format="json",
        )

        self.assertEqual(patch_response.status_code, 400)
        self.assertEqual(second.status_code, 400)
