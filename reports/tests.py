from datetime import datetime, time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from customers.models import Customer
from services.models import PaymentMethod, Service, ServiceOperations, ServicePayment
from tenants.models import Tenant


class DailySummaryPDFTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Rapor Firması', code='daily-summary-main')
        self.other_tenant = Tenant.objects.create(name='Diğer Firma', code='daily-summary-other')
        self.user = User.objects.create_user(
            email='daily-summary@example.com', password='pass123', tenant=self.tenant,
            user_type='admin', approval_status='approved',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.report_date = timezone.localdate()
        self.start = timezone.make_aware(datetime.combine(self.report_date, time(hour=9)))
        self.customer = Customer.objects.create(tenant=self.tenant, full_name='PDF Müşterisi', phone_number='05550000001')
        self.service = Service.objects.create(
            tenant=self.tenant, customer=self.customer, customer_full_name=self.customer.full_name,
            customer_phone=self.customer.phone_number, scheduled_date=self.start,
        )
        ServiceOperations.objects.create(service=self.service, name='Bakım', quantity=1, unit_price=Decimal('1250.00'))
        self.method = PaymentMethod.objects.create(tenant=self.tenant, name='Kart')
        self.payment = ServicePayment.objects.create(service=self.service, amount=Decimal('750.00'), payment_method=self.method)
        ServicePayment.objects.filter(pk=self.payment.pk).update(created_at=self.start)

        other_customer = Customer.objects.create(tenant=self.other_tenant, full_name='Başka Müşteri', phone_number='05550000002')
        other_service = Service.objects.create(
            tenant=self.other_tenant, customer=other_customer, customer_full_name=other_customer.full_name,
            customer_phone=other_customer.phone_number, scheduled_date=self.start,
        )
        ServiceOperations.objects.create(service=other_service, name='Gizli İşlem', quantity=1, unit_price=Decimal('9999.00'))

    def test_daily_summary_pdf_is_tenant_scoped(self):
        response = self.client.get(reverse('report-daily-summary-pdf'), {'date': self.report_date.isoformat()})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('gunluk_icmal_', response['Content-Disposition'])
        self.assertGreater(len(response.content), 1000)

    def test_daily_summary_rejects_invalid_date(self):
        response = self.client.get(reverse('report-daily-summary-pdf'), {'date': '14-09-2026'})

        self.assertEqual(response.status_code, 400)

    def test_daily_summary_json_is_tenant_scoped(self):
        response = self.client.get(reverse('report-daily-summary'), {'date': self.report_date.isoformat()})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total_services'], 1)
        self.assertEqual(response.data['services'][0]['customer_name'], 'PDF Müşterisi')
        self.assertEqual(str(response.data['total_revenue']), '1250.00')

    def test_daily_service_list_pdf_is_tenant_scoped(self):
        response = self.client.get(reverse('report-daily-service-list-pdf'), {'date': self.report_date.isoformat()})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('gunluk_servis_listesi_', response['Content-Disposition'])
        self.assertGreater(len(response.content), 1000)

    def test_daily_service_list_json_is_tenant_scoped(self):
        response = self.client.get(reverse('report-daily-service-list'), {'date': self.report_date.isoformat()})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total_services'], 1)
        self.assertEqual(response.data['services'][0]['customer_name'], 'PDF Müşterisi')

    def test_technician_daily_service_list_requires_same_tenant_technician(self):
        technician_user = User.objects.create_user(
            email='technician-daily-list@example.com', password='pass123', tenant=self.tenant,
            user_type='technician', approval_status='approved', first_name='PDF', last_name='Teknisyen',
        )
        technician = technician_user.technician_profile
        self.service.technician = technician
        self.service.save()

        response = self.client.get(reverse('report-daily-service-list-pdf'), {
            'date': self.report_date.isoformat(),
            'technician_id': str(technician.id),
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn('teknisyen_servis_listesi_', response['Content-Disposition'])

        other_technician_user = User.objects.create_user(
            email='other-technician-daily-list@example.com', password='pass123', tenant=self.other_tenant,
            user_type='technician', approval_status='approved',
        )
        other_response = self.client.get(reverse('report-daily-service-list-pdf'), {
            'date': self.report_date.isoformat(),
            'technician_id': str(other_technician_user.technician_profile.id),
        })
        self.assertEqual(other_response.status_code, 404)


class MyDailySummaryTests(TestCase):
    def setUp(self):
        DailySummaryPDFTests.setUp(self)
        self.technician_user = User.objects.create_user(
            email='my-summary-tech@example.com', password='pass123', tenant=self.tenant,
            user_type='technician', approval_status='approved', first_name='Kendi', last_name='Teknisyenim',
        )
        self.technician = self.technician_user.technician_profile
        self.peer_user = User.objects.create_user(
            email='my-summary-peer@example.com', password='pass123', tenant=self.tenant,
            user_type='technician', approval_status='approved',
        )
        self.service.technician = self.technician
        self.service.save()
        self.peer_service = Service.objects.create(
            tenant=self.tenant, customer=self.customer, customer_full_name='Diğer Teknisyenin Müşterisi',
            customer_phone=self.customer.phone_number, scheduled_date=self.start,
            technician=self.peer_user.technician_profile,
        )
        ServiceOperations.objects.create(service=self.peer_service, name='Görünmemesi gereken işlem', quantity=1, unit_price=Decimal('8000.00'))
        peer_payment = ServicePayment.objects.create(service=self.peer_service, amount=Decimal('3000.00'), payment_method=self.method)
        ServicePayment.objects.filter(pk=peer_payment.pk).update(created_at=self.start)
        self.client.force_authenticate(self.technician_user)

    def test_own_summary_filters_services_payments_and_totals(self):
        response = self.client.get(reverse('report-my-daily-summary'), {'date': self.report_date.isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in response.data['services']], [str(self.service.id)])
        self.assertEqual(response.data['total_services'], 1)
        self.assertEqual(response.data['total_revenue'], Decimal('1250.00'))
        self.assertEqual(response.data['collected_total'], Decimal('750.00'))
        self.assertEqual(response.data['outstanding_total'], Decimal('500.00'))
        self.assertEqual(response.data['payment_distribution'], [{'name': 'Kart', 'amount': Decimal('750.00')}])

    def test_client_cannot_select_another_technician(self):
        response = self.client.get(reverse('report-my-daily-summary'), {
            'date': self.report_date.isoformat(), 'technician_id': str(self.peer_user.technician_profile.id),
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in response.data['services']], [str(self.service.id)])

    def test_own_pdf_does_not_include_peer_service(self):
        from unittest.mock import patch
        from reports.utils import generate_daily_summary_pdf
        with patch('reports.views.generate_daily_summary_pdf', wraps=generate_daily_summary_pdf) as render:
            response = self.client.get(reverse('report-my-daily-summary-pdf'), {
                'date': self.report_date.isoformat(), 'technician_id': str(self.peer_user.technician_profile.id),
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('gunluk_icmalim_', response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'%PDF-'))
        self.assertGreater(len(response.content), 1000)
        data = render.call_args.args[0]
        self.assertEqual([row['id'] for row in data['services']], [str(self.service.id)])
        self.assertEqual(data['technician_name'], 'Kendi Teknisyenim')
        self.assertEqual(data['collected_total'], Decimal('750.00'))

    def test_missing_technician_profile_does_not_fall_back_to_tenant_report(self):
        self.client.force_authenticate(self.user)
        for name in ['report-my-daily-summary', 'report-my-daily-summary-pdf']:
            response = self.client.get(reverse(name), {'date': self.report_date.isoformat()})
            self.assertEqual(response.status_code, 403)

    def test_own_report_requires_login_and_valid_date(self):
        response = self.client.get(reverse('report-my-daily-summary'), {'date': 'invalid'})
        self.assertEqual(response.status_code, 400)
        self.client.force_authenticate(None)
        response = self.client.get(reverse('report-my-daily-summary'))
        self.assertIn(response.status_code, [401, 403])

    def test_empty_day_returns_only_zero_totals(self):
        response = self.client.get(reverse('report-my-daily-summary'), {'date': (self.report_date + timedelta(days=2)).isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['services'], [])
        self.assertEqual(response.data['total_services'], 0)
        self.assertEqual(response.data['collected_total'], Decimal('0.00'))
