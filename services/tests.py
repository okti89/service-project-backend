from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from reportlab.platypus import Paragraph

from accounts.models import User
from customers.models import Customer
from tenants.models import Tenant
from technicians.models import Technician, TechnicianPermissions
from notifications.models import Notification
from products.models import Product

from .daily_summary import send_daily_service_summaries
from .operational_alerts import send_operational_alerts

from accounting.models import Transaction

from .models import PaymentMethod, Service, ServiceOperations, ServicePayment, WarrantyCertificate
from .pdf_utils import generate_service_form_pdf
from .serializers import PublicServiceSerializer, ServiceSerializer, WarrantyCertificateSerializer
from .views import (
    _build_public_service_tracking_url,
    _build_service_pdf_filename,
    _build_service_status_whatsapp_url,
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

    def create_service_from_customer_fields(self, **overrides):
        request = self.factory.post('/api/services/admin-services/')
        request.user = self.user
        payload = {
            'customer_full_name': 'Yeni Müşteri',
            'customer_phone': '+90 555 987 65 43',
            'customer_address': 'Yeni müşteri adresi',
            'scheduled_date': timezone.now() + timedelta(days=2),
        }
        payload.update(overrides)
        serializer = ServiceSerializer(data=payload, context={'request': request})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return serializer.save(tenant=self.tenant)

    def test_create_service_automatically_creates_and_links_customer(self):
        service = self.create_service_from_customer_fields()

        customer = Customer.objects.get(
            tenant=self.tenant,
            phone_number='05559876543',
        )
        self.assertEqual(service.customer, customer)
        self.assertEqual(customer.full_name, 'Yeni Müşteri')
        self.assertEqual(customer.address, 'Yeni müşteri adresi')
        self.assertEqual(service.customer_phone, '05559876543')

    def test_create_service_links_existing_customer_with_same_phone(self):
        customer_count = Customer.objects.filter(tenant=self.tenant).count()

        service = self.create_service_from_customer_fields(
            customer_full_name='Formdaki İsim',
            customer_phone='+90 555 111 22 33',
            customer_address='Formdaki yeni adres',
        )

        self.assertEqual(service.customer, self.customer)
        self.assertEqual(Customer.objects.filter(tenant=self.tenant).count(), customer_count)
        self.assertEqual(service.customer_full_name, 'Formdaki İsim')
        self.assertEqual(service.customer_address, 'Formdaki yeni adres')

    def test_create_service_reactivates_matching_deleted_customer(self):
        self.customer.is_deleted = True
        self.customer.save(update_fields=['is_deleted', 'updated_at'])

        service = self.create_service_from_customer_fields(
            customer_phone='0555 111 22 33',
        )

        self.customer.refresh_from_db()
        self.assertEqual(service.customer, self.customer)
        self.assertFalse(self.customer.is_deleted)

    def test_public_service_serializer_uses_existing_fields_only(self):
        self.service.description = 'Internal service note'
        self.service.save(update_fields=['description'])
        data = PublicServiceSerializer(self.service).data

        self.assertEqual(data["receipt_number"], self.service.receipt_number)
        self.assertEqual(data["status_name"], "Yeni")
        self.assertNotIn("technician_status", data)
        self.assertNotIn("technician_status_updated_at", data)
        self.assertNotIn('description', data)

    def test_service_pdf_prints_fault_description_once(self):
        self.service.description = 'Replaced thermostat and tested heating'
        self.service.save(update_fields=['description'])
        rendered_text = []

        def capture_paragraph(value, style):
            rendered_text.append(value)
            return Paragraph(value, style)

        with patch('services.pdf_utils.Paragraph', side_effect=capture_paragraph):
            pdf = generate_service_form_pdf(self.service)

        self.assertTrue(pdf.getvalue().startswith(b'%PDF'))
        self.assertEqual(sum('No heat' in value for value in rendered_text), 1)
        self.assertIn('AÇIKLAMA', rendered_text)
        self.assertEqual(sum('Replaced thermostat' in value for value in rendered_text), 1)

    def test_service_pdf_uses_dash_for_empty_description(self):
        rendered_text = []

        def capture_paragraph(value, style):
            rendered_text.append(value)
            return Paragraph(value, style)

        with patch('services.pdf_utils.Paragraph', side_effect=capture_paragraph):
            generate_service_form_pdf(self.service)

        description_index = rendered_text.index('AÇIKLAMA')
        self.assertEqual(rendered_text[description_index + 1], '-')

    def test_service_description_is_saved_and_can_be_cleared(self):
        service = self.create_service_from_customer_fields(description='Replaced thermostat')
        self.assertEqual(ServiceSerializer(service).data['description'], 'Replaced thermostat')

        request = self.factory.patch(f'/api/services/admin-services/{service.id}/')
        request.user = self.user
        serializer = ServiceSerializer(
            service, data={'description': ''}, partial=True, context={'request': request},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        service.refresh_from_db()
        self.assertEqual(service.description, '')

    def test_service_description_round_trips_through_admin_api(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        url = reverse('admin-service-list-create')
        response = client.post(url, {
            'customer': str(self.customer.id),
            'fault_description': 'No heat',
            'description': 'Thermostat replaced',
            'scheduled_date': (timezone.now() + timedelta(days=2)).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['fault_description'], 'No heat')
        self.assertEqual(response.data['description'], 'Thermostat replaced')

        detail_url = reverse('admin-service-retrieve-update-destroy', args=[response.data['id']])
        response = client.patch(detail_url, {'description': ''}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['description'], '')

        response = client.get(detail_url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['fault_description'], 'No heat')
        self.assertEqual(response.data['description'], '')

    def test_service_operation_rejects_other_tenant_service_and_product(self):
        other_tenant = Tenant.objects.create(name="Other operations", code="other-operations")
        other_service = Service.objects.create(
            tenant=other_tenant,
            customer_full_name="Other customer",
            scheduled_date=timezone.now() + timedelta(days=1),
        )
        other_product = Product.objects.create(
            tenant=other_tenant,
            name="Other product",
            price="10.00",
            stock_quantity=1,
        )
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.post(
            "/api/services/service-operations/",
            {
                "service": str(other_service.id),
                "product": str(other_product.id),
                "name": "Cross tenant operation",
                "quantity": 1,
                "unit_price": 10,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ServiceOperations.objects.filter(name="Cross tenant operation").exists())

    def test_inventory_product_can_be_added_as_service_operation(self):
        product = Product.objects.create(
            tenant=self.tenant,
            name="Sirkülasyon Pompası",
            price="6500.00",
            stock_quantity=2,
        )
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.post(
            "/api/services/service-operations/",
            {
                "service": str(self.service.id),
                "product": str(product.id),
                "name": product.name,
                "description": "Pompa değişimi yapıldı",
                "quantity": 1,
                "unit_price": 6500,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        operation = ServiceOperations.objects.get(pk=response.data["id"])
        self.assertEqual(operation.product, product)
        self.assertEqual(operation.tenant, self.tenant)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 1)

    def test_payment_uses_service_tenant_when_customer_is_missing(self):
        self.service.customer = None
        self.service.save(update_fields=['customer'])
        ServiceOperations.objects.create(
            tenant=self.tenant,
            service=self.service,
            name='Bakim',
            quantity=1,
            unit_price=Decimal('100.00'),
        )
        payment_method = PaymentMethod.objects.create(tenant=self.tenant, name='Nakit')
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.post(
            '/api/services/service-payments/',
            {
                'service': str(self.service.id),
                'payment_method': payment_method.pk,
                'amount': '100.00',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        payment = ServicePayment.objects.get(pk=response.data['id'])
        self.assertEqual(payment.tenant, self.tenant)
        income = Transaction.objects.get(
            receipt_number=Transaction.normalize_receipt_number(payment._transaction_receipt_ref()),
            transaction_type='income',
        )
        self.assertEqual(income.tenant, self.tenant)
        self.assertEqual(income.account.tenant, self.tenant)

        list_response = client.get('/api/services/service-payments/')
        self.assertEqual(list_response.status_code, 200)
        self.assertIn(str(payment.id), [item['id'] for item in list_response.data])

    def test_payment_rejects_service_owned_by_another_tenant(self):
        other_tenant = Tenant.objects.create(name='Other Tenant', code='other-payment-tenant')
        other_service = Service.objects.create(
            tenant=other_tenant,
            customer_full_name='Other Customer',
            scheduled_date=timezone.now() + timedelta(days=1),
        )
        ServiceOperations.objects.create(
            tenant=other_tenant,
            service=other_service,
            name='Bakim',
            quantity=1,
            unit_price=Decimal('100.00'),
        )
        payment_method = PaymentMethod.objects.create(tenant=self.tenant, name='Nakit')
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.post(
            '/api/services/service-payments/',
            {
                'service': str(other_service.id),
                'payment_method': payment_method.pk,
                'amount': '100.00',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('service', response.data)
        self.assertFalse(ServicePayment.objects.filter(service=other_service).exists())

    def test_status_change_notifies_only_admins_in_service_tenant(self):
        same_tenant_admin = User.objects.create_user(
            email='same-tenant-admin@example.com',
            password='pass123',
            tenant=self.tenant,
            user_type='admin',
        )
        other_tenant = Tenant.objects.create(name='Other Notification Tenant', code='other-notification-tenant')
        other_tenant_admin = User.objects.create_user(
            email='other-tenant-admin@example.com',
            password='pass123',
            tenant=other_tenant,
            user_type='admin',
        )
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.patch(
            f'/api/services/technician-services/{self.service.id}/',
            {'service_status': 'completed'},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(
            Notification.objects.filter(
                user=same_tenant_admin,
                tenant=self.tenant,
                related_id=str(self.service.id),
            ).exists()
        )
        self.assertFalse(Notification.objects.filter(user=other_tenant_admin).exists())

    def test_overdue_service_filter_is_tenant_scoped_and_excludes_closed_services(self):
        admin = User.objects.create_user(
            email='overdue-admin@example.com',
            password='pass123',
            tenant=self.tenant,
            user_type='admin',
        )
        overdue_service = Service.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            customer_full_name='Overdue Customer',
            scheduled_date=timezone.now() - timedelta(hours=2),
        )
        completed_service = Service.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            customer_full_name='Completed Customer',
            scheduled_date=timezone.now() - timedelta(hours=3),
        )
        completed_service.service_status = 'completed'
        completed_service.save()
        other_tenant = Tenant.objects.create(name='Other Overdue Tenant', code='other-overdue-tenant')
        other_service = Service.objects.create(
            tenant=other_tenant,
            customer_full_name='Other Overdue Customer',
            scheduled_date=timezone.now() - timedelta(hours=4),
        )
        client = APIClient()
        client.force_authenticate(admin)

        response = client.get('/api/services/admin-services/', {'overdue': 'true'})

        self.assertEqual(response.status_code, 200, response.data)
        service_ids = {item['id'] for item in response.data}
        self.assertIn(str(overdue_service.id), service_ids)
        self.assertNotIn(str(self.service.id), service_ids)
        self.assertNotIn(str(completed_service.id), service_ids)
        self.assertNotIn(str(other_service.id), service_ids)

    def test_model_labels_preserve_turkish_characters(self):
        self.assertEqual(Service._meta.get_field('device_type').verbose_name, 'Cihaz Türü')
        self.assertEqual(Service._meta.get_field('device_brand').verbose_name, 'Cihaz Markası')
        self.assertEqual(Service._meta.get_field('status').related_model._meta.verbose_name_plural, 'Servis Durumları')

    def test_only_admin_can_delete_service(self):
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.delete(f"/api/services/admin-services/{self.service.id}/")

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Service.objects.filter(pk=self.service.id).exists())

    def test_admin_delete_restores_used_product_stock(self):
        admin = User.objects.create_user(
            email="admin-delete@example.com",
            password="pass123",
            tenant=self.tenant,
            user_type="admin",
        )
        product = Product.objects.create(
            tenant=self.tenant,
            name="Silinecek Servis Ürünü",
            price="100.00",
            stock_quantity=2,
        )
        ServiceOperations.objects.create(
            tenant=self.tenant,
            service=self.service,
            product=product,
            name=product.name,
            quantity=1,
            unit_price=product.price,
        )
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 1)

        client = APIClient()
        client.force_authenticate(admin)
        response = client.delete(f"/api/services/admin-services/{self.service.id}/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(Service.objects.filter(pk=self.service.id).exists())
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 2)

    def test_deleting_cancelled_service_does_not_restore_stock_twice(self):
        admin = User.objects.create_user(
            email="admin-cancelled-delete@example.com",
            password="pass123",
            tenant=self.tenant,
            user_type="admin",
        )
        product = Product.objects.create(
            tenant=self.tenant,
            name="İptal Edilen Servis Ürünü",
            price="100.00",
            stock_quantity=2,
        )
        ServiceOperations.objects.create(
            tenant=self.tenant,
            service=self.service,
            product=product,
            name=product.name,
            quantity=1,
            unit_price=product.price,
        )
        self.service.service_status = "cancelled"
        self.service.save()
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 2)

        client = APIClient()
        client.force_authenticate(admin)
        response = client.delete(f"/api/services/admin-services/{self.service.id}/")

        self.assertEqual(response.status_code, 200, response.data)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 2)

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

    def test_public_tracking_link_uses_service_id_without_access_token(self):
        request = self.factory.get(
            "/api/services/admin-services/",
            HTTP_ORIGIN="https://panel.example.com",
        )

        tracking_url = _build_public_service_tracking_url(self.service, request=request)

        self.assertEqual(tracking_url, f"https://panel.example.com/service-tracking/{self.service.id}/")

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

    def test_allows_staff_user_recognized_as_admin_by_mobile(self):
        staff_user = User.objects.create_user(
            email="weekly-staff@example.com",
            password="pass123",
            tenant=self.tenant,
            user_type="technician",
            is_staff=True,
        )
        self.client.force_authenticate(staff_user)

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

    def test_manager_receives_one_daily_summary_for_multiple_overdue_services(self):
        for hours_ago in (1, 2, 3):
            self.create_service(
                technician=self.technician,
                scheduled_date=self.now - timedelta(hours=hours_ago),
                customer_full_name=f'Müşteri {hours_ago}',
            )

        result = send_operational_alerts(
            now=self.now,
            include_unassigned=False,
            include_technician_schedule_reminders=False,
            include_technician_status_reminders=False,
            include_receivable=False,
        )

        self.assertEqual(result['overdue'], 1)
        notification = Notification.objects.get(user=self.manager, title='Geciken Servis Uyarısı')
        self.assertIn('3 geciken servis', notification.message)
        self.assertIn('Müşteriler: Müşteri 3, Müşteri 2, Müşteri 1.', notification.message)
        self.assertEqual(notification.related_screen, 'overdue_services')
        self.assertIsNone(notification.related_id)

        repeated_result = send_operational_alerts(
            now=self.now,
            include_unassigned=False,
            include_technician_schedule_reminders=False,
            include_technician_status_reminders=False,
            include_receivable=False,
        )
        self.assertEqual(repeated_result['total_sent'], 0)

    def test_technician_overdue_reminder_is_sent_only_once_for_service(self):
        service = self.create_service(
            technician=self.technician,
            scheduled_date=self.now - timedelta(hours=2),
        )

        first_result = send_operational_alerts(
            now=self.now,
            include_unassigned=False,
            include_overdue_manager_alerts=False,
            include_technician_schedule_reminders=False,
            include_receivable=False,
        )
        next_day_result = send_operational_alerts(
            now=self.now + timedelta(days=1),
            include_unassigned=False,
            include_overdue_manager_alerts=False,
            include_technician_schedule_reminders=False,
            include_receivable=False,
        )

        self.assertEqual(first_result['overdue'], 1)
        self.assertEqual(next_day_result['overdue'], 0)
        self.assertEqual(
            Notification.objects.filter(
                user=self.technician_user,
                related_id=str(service.id),
                title='Servis Durumu Güncelleme Hatırlatması',
            ).count(),
            1,
        )
