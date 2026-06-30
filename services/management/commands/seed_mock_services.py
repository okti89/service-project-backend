"""Backend tarafinda Services uygulamasi icin mock (ornek) veri uretir.

Kullanim:
    python manage.py seed_mock_services

Opsiyonel parametreler:
    --tenant-id   : Mock veri sadece belirtilen tenant icin uretilir.
    --reset       : Mevcut servis ve iliskili kayitlari silip bastan uretir.
    --count       : Olusturulacak servis sayisi (varsayilan: 15).

Tenant icin ilk aktif Tenant secilir; yoksa komut hata verir.
"""

import random
import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from customers.models import Customer
from services.models import (
    Brand,
    DeviceType,
    Model,
    PaymentMethod,
    Service,
    ServiceOperations,
    ServicePayment,
    ServiceStatus,
)
from tenants.models import Tenant
from technicians.models import Technician


CUSTOMER_SEEDS = [
    ('Ahmet Yilmaz', '+90 532 111 11 11', 'ahmet.yilmaz@example.com', 'Atasehir, Istanbul'),
    ('Mehmet Demir', '+90 533 222 22 22', 'mehmet.demir@example.com', 'Kadikoy, Istanbul'),
    ('Ayse Kaya', '+90 535 333 33 33', 'ayse.kaya@example.com', 'Besiktas, Istanbul'),
    ('Fatma Celik', '+90 536 444 44 44', 'fatma.celik@example.com', 'Sisli, Istanbul'),
    ('Ali Ozturk', '+90 537 555 55 55', 'ali.ozturk@example.com', 'Beyoglu, Istanbul'),
    ('Zeynep Arslan', '+90 538 666 66 66', 'zeynep.arslan@example.com', 'Bakirkoy, Istanbul'),
    ('Hasan Polat', '+90 539 777 77 77', 'hasan.polat@example.com', 'Esenyurt, Istanbul'),
    ('Emine Sahin', '+90 542 888 88 88', 'emine.sahin@example.com', 'Avcilar, Istanbul'),
    ('Mustafa Aydin', '+90 543 999 99 99', 'mustafa.aydin@example.com', 'Maltepe, Istanbul'),
    ('Hatice Yildiz', '+90 544 010 10 10', 'hatice.yildiz@example.com', 'Pendik, Istanbul'),
    ('Osman Korkmaz', '+90 545 020 20 20', 'osman.korkmaz@example.com', 'Kartal, Istanbul'),
    ('Selin Aksoy', '+90 546 030 30 30', 'selin.aksoy@example.com', 'Uskudar, Istanbul'),
    ('Burak Dogan', '+90 547 040 40 40', 'burak.dogan@example.com', 'Umraniye, Istanbul'),
    ('Cansu Yavuz', '+90 548 050 50 50', 'cansu.yavuz@example.com', 'Sancaktepe, Istanbul'),
    ('Tolga Acar', '+90 549 060 60 60', 'tolga.acar@example.com', 'Cekmekoy, Istanbul'),
]


DEVICE_TYPES = ['Telefon', 'Tablet', 'Bilgisayar', 'Televizyon', 'Saat']

BRAND_SEEDS = [
    'Samsung', 'Apple', 'Xiaomi', 'Huawei', 'Oppo', 'LG', 'Sony', 'Asus', 'Lenovo', 'Toshiba',
]

MODEL_SEEDS_BY_BRAND = {
    'Samsung': ['Galaxy S22', 'Galaxy S21', 'Galaxy A52', 'Galaxy A72', 'Galaxy Tab S8'],
    'Apple': ['iPhone 12', 'iPhone 13', 'iPhone 14', 'iPhone 15', 'iPad Pro'],
    'Xiaomi': ['Redmi Note 12', 'Mi 11', 'Mi 13', 'Redmi 12', 'Poco X5'],
    'Huawei': ['P40 Pro', 'Mate 50', 'Nova 11', 'P50', 'MatePad'],
    'Oppo': ['Reno 8', 'A78', 'Find X5', 'Reno 10', 'A58'],
    'LG': ['Velvet', 'K62', 'Stylo 7', 'G8', 'V60'],
    'Sony': ['Xperia 5', 'Xperia 10', 'Xperia 1', 'Xperia L4', 'Xperia Pro'],
    'Asus': ['Zenfone 9', 'ROG Phone 6', 'VivoBook', 'ZenPad', 'ExpertBook'],
    'Lenovo': ['ThinkPad X1', 'IdeaPad 5', 'Legion 5', 'Yoga Slim', 'Tab P11'],
    'Toshiba': ['Satellite Pro', 'Tecra', 'Portégé', 'Kirabook', 'Dynabook'],
}

PAYMENT_METHOD_SEEDS = [
    ('Nakit', False),
    ('Kredi Karti', True),
    ('Banka Havalesi', False),
    ('Temassiz Kart', False),
]

OPERATION_SEEDS = [
    ('Ekran Degisimi', Decimal('2500.00')),
    ('Batarya Degisimi', Decimal('850.00')),
    ('Sarj Soketi Tamiri', Decimal('600.00')),
    ('Kamera Modulu Degisimi', Decimal('1450.00')),
    ('Yazilim Güncelleme', Decimal('350.00')),
    ('Anakart Tamiri', Decimal('3200.00')),
    ('Hoparlör Degisimi', Decimal('420.00')),
    ('Klavye Degisimi', Decimal('780.00')),
    ('Sivi Hasar Onarimi', Decimal('1850.00')),
    ('Temizlik & Bakim', Decimal('300.00')),
]

STATUS_CODES = ['new', 'assigned', 'in_progress', 'completed', 'postponed', 'cancelled']

FAULT_DESCRIPTIONS = [
    'Ekran kirik ve dokunmatik calismiyor',
    'Cihaz acilmiyor, sarj soketinden supheleniyoruz',
    'Batarya cok cabuk tukeniyor',
    'Kamera bulanik cekiyor',
    'Wi-Fi baglanmiyor',
    'Sivi doku aldi, acil mudahale gerekli',
    'Yazilim guncellemesi sonrasi sikinti var',
    'Sistem cok yavas calisiyor',
    'Klavye tuslari calismiyor',
    'Fan sesi anormal seviyede',
]


class Command(BaseCommand):
    help = 'Services uygulamasi icin ornek veri uretir.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant-id',
            type=str,
            default=None,
            help='Mock verilerin olusturulacagi tenant UUID.',
        )
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Mevcut servisleri ve bagli kayitlari silip bastan uretir.',
        )
        parser.add_argument(
            '--count',
            type=int,
            default=15,
            help='Olusturulacak servis sayisi (varsayilan: 15).',
        )

    def handle(self, *args, **options):
        tenant = self._resolve_tenant(options.get('tenant_id'))
        count = max(1, options['count'])

        with transaction.atomic():
            if options['reset']:
                self._reset_for_tenant(tenant)
                self.stdout.write(self.style.WARNING(
                    f"'{tenant}' tenantina ait mevcut servis kayitlari temizlendi."
                ))

            device_types = self._ensure_device_types(tenant)
            brands, models_by_brand = self._ensure_brands_and_models(tenant)
            payment_methods = self._ensure_payment_methods(tenant)
            statuses_by_code = self._ensure_statuses(tenant)
            technicians = self._ensure_technicians(tenant)
            customers = self._ensure_customers(tenant)

            self._ensure_services(
                tenant=tenant,
                count=count,
                device_types=device_types,
                brands=brands,
                models_by_brand=models_by_brand,
                payment_methods=payment_methods,
                statuses_by_code=statuses_by_code,
                technicians=technicians,
                customers=customers,
            )

        self.stdout.write(self.style.SUCCESS(
            f"'{tenant}' tenant'i icin {count} servis mock verisi basariyla olusturuldu."
        ))

    def _resolve_tenant(self, tenant_id):
        if tenant_id:
            try:
                return Tenant.objects.get(id=tenant_id)
            except (Tenant.DoesNotExist, ValueError):
                raise CommandError(f"Belirtilen tenant bulunamadi: {tenant_id}")

        tenant = Tenant.objects.filter(is_active=True).first() or Tenant.objects.first()
        if not tenant:
            raise CommandError('Veritabaninda hic tenant yok. Once bir tenant olusturun.')
        return tenant

    def _reset_for_tenant(self, tenant):
        Service.objects.filter(tenant=tenant).delete()

    def _ensure_device_types(self, tenant):
        result = []
        for index, name in enumerate(DEVICE_TYPES):
            obj, _ = DeviceType.objects.get_or_create(
                tenant=tenant,
                name=name,
                defaults={'is_default': index == 0},
            )
            result.append(obj)
        return result

    def _ensure_brands_and_models(self, tenant):
        brands = []
        models_by_brand = {}
        for name in BRAND_SEEDS:
            brand, _ = Brand.objects.get_or_create(
                tenant=tenant,
                name=name,
                defaults={'is_default': False},
            )
            brands.append(brand)
            models_by_brand[brand.id] = []
            for model_name in MODEL_SEEDS_BY_BRAND.get(name, []):
                model_obj, _ = Model.objects.get_or_create(
                    tenant=tenant,
                    brand=brand,
                    name=model_name,
                    defaults={'is_default': False},
                )
                models_by_brand[brand.id].append(model_obj)
        return brands, models_by_brand

    def _ensure_payment_methods(self, tenant):
        result = []
        for index, (name, is_default) in enumerate(PAYMENT_METHOD_SEEDS):
            obj, _ = PaymentMethod.objects.get_or_create(
                tenant=tenant,
                name=name,
                defaults={
                    'is_default': is_default,
                    'bank_name': f'{name} Banka' if 'Banka' in name else '',
                    'account_holder': 'Demo Ticaret Ltd.',
                    'iban': f'TR{uuid.uuid4().hex[:24].upper()}',
                },
            )
            result.append(obj)
        return result

    def _ensure_statuses(self, tenant):
        """Tenant icin varsayilan durumlari olusturur."""
        from services.models import DEFAULT_SERVICE_STATUSES

        result = {}
        for index, (code, name, color, sort_order, is_terminal) in enumerate(DEFAULT_SERVICE_STATUSES):
            obj, _ = ServiceStatus.objects.get_or_create(
                tenant=tenant,
                code=code,
                defaults={
                    'name': name,
                    'color': color,
                    'sort_order': sort_order,
                    'is_default': index == 0,
                    'is_terminal': is_terminal,
                    'is_active': True,
                },
            )
            result[code] = obj
        return result

    def _ensure_technicians(self, tenant):
        """Tenant altinda en az bir aktif teknisyen olmasi garanti edilir."""
        existing = list(Technician.objects.filter(user__tenant=tenant))
        if existing:
            return existing

        from django.contrib.auth import get_user_model

        User = get_user_model()
        sample_technicians = [
            ('Teknisyen Demo Bir', 'tech1.demo@example.com', '+90 532 100 10 10'),
            ('Teknisyen Demo Iki', 'tech2.demo@example.com', '+90 532 200 20 20'),
            ('Teknisyen Demo Uc', 'tech3.demo@example.com', '+90 532 300 30 30'),
        ]
        result = []
        for full_name, email, phone in sample_technicians:
            first, _, last = full_name.partition(' ')
            user, _ = User.objects.get_or_create(
                email=email,
                defaults={
                    'tenant': tenant,
                    'first_name': first,
                    'last_name': last,
                    'phone_number': phone,
                    'is_active': True,
                    'user_type': 'technician',
                },
            )
            technician, _ = Technician.objects.get_or_create(
                user=user,
                defaults={
                    'tenant': tenant,
                    'hire_date': timezone.now().date(),
                    'status': 'available',
                    'is_online': False,
                },
            )
            result.append(technician)
        return result

    def _ensure_customers(self, tenant):
        result = []
        for full_name, phone, email, address in CUSTOMER_SEEDS:
            customer, _ = Customer.objects.get_or_create(
                tenant=tenant,
                phone_number=phone,
                defaults={
                    'full_name': full_name,
                    'email': email,
                    'address': address,
                },
            )
            result.append(customer)
        return result

    def _ensure_services(
        self,
        *,
        tenant,
        count,
        device_types,
        brands,
        models_by_brand,
        payment_methods,
        statuses_by_code,
        technicians,
        customers,
    ):
        now = timezone.now()
        for index in range(count):
            customer = random.choice(customers)
            brand = random.choice(brands)
            model_options = models_by_brand.get(brand.id) or []
            device_model = random.choice(model_options) if model_options else None
            device_type = random.choice(device_types)
            technician = random.choice(technicians) if technicians else None
            status_code = random.choice(STATUS_CODES)
            status = statuses_by_code.get(status_code)
            scheduled_offset = timedelta(days=random.randint(-10, 10))
            scheduled_date = now + scheduled_offset

            service = Service.objects.create(
                tenant=tenant,
                customer=customer,
                customer_phone=customer.phone_number,
                customer_full_name=customer.full_name,
                customer_address=customer.address,
                device_type=device_type,
                device_brand=brand,
                device_model=device_model,
                technician=technician,
                status=status,
                scheduled_date=scheduled_date,
                fault_description=random.choice(FAULT_DESCRIPTIONS),
            )

            self._ensure_service_operations(service, tenant)
            if status_code == 'completed':
                self._ensure_service_payment(service, tenant, payment_methods)

    def _ensure_service_operations(self, service, tenant):
        """Her servis icin 1-3 islem satiri uretir."""
        for name, unit_price in random.sample(OPERATION_SEEDS, k=random.randint(1, 3)):
            quantity = random.randint(1, 3)
            ServiceOperations.objects.create(
                tenant=tenant,
                service=service,
                name=name,
                description=name,
                quantity=quantity,
                unit_price=unit_price,
            )

    def _ensure_service_payment(self, service, tenant, payment_methods):
        """Tamamlanan servisler icin odeme kaydi."""
        total = sum(
            (item.unit_price or Decimal('0')) * item.quantity
            for item in service.items.all()
        )
        if total <= 0:
            return
        method = next((m for m in payment_methods if m.is_default), payment_methods[0])
        ServicePayment.objects.create(
            tenant=tenant,
            service=service,
            amount=total,
            payment_method=method,
            note='Mock odeme kaydi',
        )
