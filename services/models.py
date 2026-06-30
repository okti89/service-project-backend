from django.db import transaction
import logging
import random
import string
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, models
from django.conf import settings
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.utils import timezone

from customers.models import Customer
from products.models import StockMovement
from technicians.models import Technician
from core.utils import tenant_directory_path

from .utils import process_service_image as process_image


logger = logging.getLogger(__name__)

def resolve_technician_user(service):
    if service.technician and service.technician.user:
        return service.technician.user

    tenant = getattr(getattr(service, "customer", None), "tenant", None)

    qs = Technician.objects.select_related('user').filter(user__is_active=True)

    if tenant:
        qs = qs.filter(user__tenant=tenant)

    tech = qs.first()
    if tech:
        return tech.user

    User = get_user_model()
    qs = User.objects.filter(is_active=True)

    if tenant:
        qs = qs.filter(tenant=tenant)

    return qs.order_by('-is_staff', 'date_joined').first()

    
def create_stock_movement(service, product, qty, movement_type, reason):
    if not product or qty <= 0:
        return

    technician_user = resolve_technician_user(service)
    if not technician_user:
        return

    StockMovement.objects.create(
        technician=technician_user,
        product=product,
        movement_type=movement_type,
        quantity=qty,
        description=f"Servis #{service.receipt_number} - {reason}"
    )


class DeviceType(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=50)
    is_default = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self.is_default:
            DeviceType.objects.exclude(id=self.id).update(is_default=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Brand(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='service_brands', null=True, blank=True)
    name = models.CharField(max_length=50, verbose_name='Marka Adı')
    is_default = models.BooleanField(default=False, verbose_name='Varsayılan Marka Mu?')
    def __str__(self):
        return self.name
    class Meta:
        verbose_name = 'Marka'
        verbose_name_plural = 'Markalar'


class Model(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='service_models', null=True, blank=True)
    name = models.CharField(max_length=50, verbose_name='Model Adı')
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, verbose_name='Marka')
    is_default = models.BooleanField(default=False, verbose_name='Varsayılan Model Mu?')
    def __str__(self):
        return self.name
    class Meta:
        verbose_name = 'Model'
        verbose_name_plural = 'Modeller'


DEFAULT_SERVICE_STATUSES = [
    ('new', 'Yeni', '#16A34A', 10, False),
    ('assigned', 'Atandı', '#2563EB', 20, False),
    ('in_progress', 'İşlemde', '#F59E0B', 30, False),
    ('postponed', 'Ertelendi', '#7C3AED', 40, False),
    ('completed', 'Tamamlandı', '#16A34A', 50, True),
    ('cancelled', 'İptal Edildi', '#DC2626', 60, True),
]


class ServiceStatus(models.Model):
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='service_statuses',
        null=True,
        blank=True,
    )
    code = models.SlugField(max_length=30)
    name = models.CharField(max_length=80)
    color = models.CharField(max_length=20, default='#6B7280')
    sort_order = models.PositiveIntegerField(default=0)
    is_default = models.BooleanField(default=False)
    is_terminal = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Servis Durumu'
        verbose_name_plural = 'Servis Durumlari'
        ordering = ['sort_order', 'name']
        unique_together = ('tenant', 'code')
        indexes = [
            models.Index(fields=['tenant', 'code']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return self.name


class Service(models.Model):
    STATUS_CODE_CHOICES = [
        ('new', 'Yeni'),
        ('assigned', 'Teknisyen Atandı'),
        ('in_progress', 'İşlemde'),
        ('postponed', 'Ertelendi'),
        ('completed', 'Tamamlandı'),
        ('cancelled', 'İptal'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='tenant_services', null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, blank=True, null=True, related_name='services', verbose_name='Müşteri')
    customer_phone = models.CharField(max_length=20, blank=True, null=True, verbose_name='Müşteri Telefonu')
    customer_full_name = models.CharField(max_length=200, blank=True, null=True, verbose_name='Müşteri Adı Soyadı')
    customer_address = models.TextField(verbose_name='Müşteri Adresi', blank=True, null=True)
    fault_description = models.TextField(verbose_name='Arıza Açıklaması', blank=True, null=True)
    # CharField yapısı kullanıcı talebiyle korunuyor.
    device_type = models.ForeignKey(DeviceType, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='Cihaz TÃ¼rÃ¼')
    device_brand = models.ForeignKey(Brand, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='Cihaz MarkasÄ±')
    device_model = models.ForeignKey(Model, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='Cihaz Modeli')
    technician = models.ForeignKey(Technician, on_delete=models.SET_NULL, null=True, blank=True, related_name='services', verbose_name='Teknisyen')

    status = models.ForeignKey(
        ServiceStatus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='services',
        verbose_name='Servis Durumu',
    )
    receipt_number = models.CharField(max_length=20, unique=True, editable=False, verbose_name='Fatura Numarası', null=True, blank=True)
    scheduled_date = models.DateTimeField(verbose_name='Randevu Tarihi')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Oluşturulma Tarihi')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Güncellenme Tarihi')
    class Meta:
        verbose_name = 'Servis'
        verbose_name_plural = 'Servisler'
        ordering = ['-scheduled_date']

    def __str__(self):
        assignee = 'Teknisyen Ataması Yapılmadı'
        if self.technician:
            assignee = str(self.technician)
        return f"{self.customer_full_name} - {assignee} - {self.service_status}"

    @property
    def service_status(self):
        return getattr(self, '_pending_service_status_code', None) or getattr(self.status, 'code', None) or 'new'

    @service_status.setter
    def service_status(self, value):
        self._pending_service_status_code = str(value or '').strip() or 'new'

    def _status_tenant(self):
        return self.tenant or getattr(getattr(self, 'customer', None), 'tenant', None)

    def _resolve_status(self, code):
        code = str(code or '').strip() or 'new'
        tenant = self._status_tenant()
        status = None
        if tenant:
            status = ServiceStatus.objects.filter(tenant=tenant, code=code, is_active=True).first()
        if not status:
            status = ServiceStatus.objects.filter(tenant__isnull=True, code=code, is_active=True).first()
        if status:
            return status

        defaults = {
            item_code: {
                'name': name,
                'color': color,
                'sort_order': sort_order,
                'is_default': item_code == 'new',
                'is_terminal': is_terminal,
                'is_active': True,
            }
            for item_code, name, color, sort_order, is_terminal in DEFAULT_SERVICE_STATUSES
        }
        values = defaults.get(code, {
            'name': code.replace('_', ' ').title(),
            'color': '#6B7280',
            'sort_order': 999,
            'is_default': False,
            'is_terminal': False,
            'is_active': True,
        })
        return ServiceStatus.objects.create(tenant=tenant, code=code, **values)
    @staticmethod
    def _generate_receipt_number():
        random_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        return f"{timezone.now().strftime('%Y%m%d')}-{random_code}"

    def _sync_stock_for_cancel_transition(self, old_status):
        if old_status == self.service_status:
            return

        if self.service_status not in ['cancelled', old_status]:
            return

        movement_type = None
        reason = None

        if old_status != 'cancelled' and self.service_status == 'cancelled':
            movement_type = 'return'
            reason = 'servis iptal'
        elif old_status == 'cancelled' and self.service_status != 'cancelled':
            movement_type = 'out'
            reason = 'iptal geri alma'
        else:
            return

        technician_user = resolve_technician_user(self)
        if not technician_user:
            return

        quantity_map = {}

        for item in self.items.select_related('product').all():
            if item.product and item.quantity > 0:
                quantity_map[item.product] = quantity_map.get(item.product, 0) + item.quantity

        for product, qty in quantity_map.items():
            create_stock_movement(self, product, qty, movement_type, reason)
    def _normalize_assignment_status(self):
        pending_status = getattr(self, '_pending_service_status_code', None)
        status = str(pending_status or self.service_status or '').strip() or 'new'
        has_technician = bool(self.technician_id)

        # Teknisyen yoksa sadece "atandi" durumu "yeni"ye cekilir.
        # "islemde/tamamlandi/iptal" gibi akislari geriye sarmayiz.
        if not has_technician and status == 'assigned':
            self.service_status = 'new'
            return

        # Sadece yeni olusturulan kayitlarda ve status acikca secilmemisse
        # teknisyen atamasi "assigned" durumunu otomatiklestirir.
        if has_technician and status == 'new' and pending_status is None and not self.pk:
            self.service_status = 'assigned'
            return

        self.service_status = status

    def save(self, *args, **kwargs):
        old_status = None
        if self.pk:
            old = Service.objects.select_related('status').filter(pk=self.pk).first()
            old_status = old.service_status if old else None
        self._normalize_assignment_status()
        self.status = self._resolve_status(self.service_status)
        self._pending_service_status_code = self.status.code if self.status_id else 'new'
        if not self.receipt_number:
            self.receipt_number = self._generate_receipt_number()
        super().save(*args, **kwargs)
        self._sync_stock_for_cancel_transition(old_status)

class ServiceSignature(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='service_signatures', null=True, blank=True)
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='signatures', verbose_name='Servis')
    customer_signature = models.ImageField(upload_to=tenant_directory_path, blank=True, null=True, verbose_name='Müşteri İmzası')
    technician_signature = models.ImageField(upload_to=tenant_directory_path, blank=True, null=True, verbose_name='Teknisyen İmzası')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Oluşturulma Tarihi')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Güncellenme Tarihi')

    class Meta:
        verbose_name = 'Servis İmzası'
        verbose_name_plural = 'Servis İmzaları'
    def _process_signatures(self):
        if self.customer_signature:
            try:
                if self._state.adding:
                    self.customer_signature = process_image(self.customer_signature)
                else:
                    old_instance = Service.objects.get(pk=self.pk)
                    if old_instance.customer_signature != self.customer_signature:
                        self.customer_signature = process_image(self.customer_signature)
            except Service.DoesNotExist:
                logger.warning('Service imza işleme: eski kayıt bulunamadı. service_id=%s', self.pk)
            except Exception:
                logger.exception('Müşteri imzası işlenemedi. service_id=%s', self.pk)

        if self.technician_signature:
            try:
                if self._state.adding:
                    self.technician_signature = process_image(self.technician_signature)
                else:
                    old_instance = Service.objects.get(pk=self.pk)
                    if old_instance.technician_signature != self.technician_signature:
                        self.technician_signature = process_image(self.technician_signature)
            except Service.DoesNotExist:
                logger.warning('Service imza işleme: eski kayıt bulunamadı. service_id=%s', self.pk)
            except Exception:
                logger.exception('Teknisyen imzası işlenemedi. service_id=%s', self.pk)




class WarrantyCertificate(models.Model):
    STATUS_CHOICES = [
        ('active', 'Aktif'),
        ('expired', 'Süresi Doldu'),
        ('void', 'Geçersiz'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='warranty_certificates', null=True, blank=True)
    service = models.OneToOneField(
        Service,
        on_delete=models.CASCADE,
        related_name='warranty_certificate',
        verbose_name='Servis',
    )
    certificate_no = models.CharField(max_length=24, unique=True, editable=False, verbose_name='Belge No')
    warranty_months = models.PositiveIntegerField(default=24, verbose_name='Garanti Süresi (Ay)')
    DEFAULT_COVERAGE_DETAILS = (
        "Garanti Şartları:\n"
        "• Bu belge, servis kapsamında yapılan işçilik ve/veya değiştirilen parçalar için geçerlidir.\n"
        "• Garanti süresi belge üzerindeki başlangıç ve bitiş tarihleri arasında geçerlidir.\n"
        "• Kullanıcı hatası, darbe, sıvı teması, yetkisiz müdahale ve yanlış kullanım durumları garanti kapsamı dışındadır.\n"
        "• Garanti sadece bu servis kaydında belirtilen işlem ve parçaları kapsar.\n"
        "• Garanti değerlendirmesi, teknik inceleme sonucuna göre yapılır."
    )

    coverage_details = models.TextField(
        blank=True,
        null=True,
        default=DEFAULT_COVERAGE_DETAILS,
        verbose_name='Garanti Kapsamı (Madde Madde)',
        help_text='Her satıra bir madde yazabilirsiniz.',
    )
    start_date = models.DateField(verbose_name='Başlangıç Tarihi')
    end_date = models.DateField(verbose_name='Bitiş Tarihi')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name='Durum')
    covered_operations = models.ManyToManyField('ServiceOperations', verbose_name='Kapsanan İşlemler')
    issued_at = models.DateTimeField(auto_now_add=True, verbose_name='Oluşturulma Tarihi')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Güncellenme Tarihi')

    class Meta:
        verbose_name = 'Garanti Belgesi'
        verbose_name_plural = 'Garanti Belgeleri'
        ordering = ['-issued_at']

    def __str__(self):
        return f"{self.certificate_no} - {self.service.receipt_number}"

    @staticmethod
    def _add_months(source_date, months):
        month_index = (source_date.month - 1) + months
        year = source_date.year + (month_index // 12)
        month = (month_index % 12) + 1

        month_days = [
            31,
            29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
            31,
            30,
            31,
            30,
            31,
            31,
            30,
            31,
            30,
            31,
        ]
        day = min(source_date.day, month_days[month - 1])
        return date(year, month, day)

    @staticmethod
    def _generate_certificate_no():
        return 'WRN-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

    def save(self, *args, **kwargs):
        if not self.certificate_no:
            max_retry = 8
            for _ in range(max_retry):
                candidate = self._generate_certificate_no()
                if not WarrantyCertificate.objects.filter(certificate_no=candidate).exists():
                    self.certificate_no = candidate
                    break
            if not self.certificate_no:
                raise IntegrityError('Benzersiz garanti belge numarası üretilemedi.')

        if not self.start_date:
            self.start_date = timezone.localdate()

        if self.warranty_months <= 0:
            self.warranty_months = 1

        self.end_date = self._add_months(self.start_date, self.warranty_months)

        if self.status != 'void':
            self.status = 'expired' if self.end_date < timezone.localdate() else 'active'

        super().save(*args, **kwargs)

class ServiceOperations(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='service_operations_list', null=True, blank=True)
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='items', verbose_name='Servis')
    name = models.CharField(max_length=255, null=True, blank=True, verbose_name='İşlem Adı')
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='service_operations',
        verbose_name='Ürün/Malzeme'
    )
    description = models.CharField(max_length=255, verbose_name='İşlem/Parça Açıklaması', blank=True)
    quantity = models.PositiveIntegerField(default=1, verbose_name='Adet')
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Birim Fiyat', blank=True, null=True)

    @property
    def total_price(self):
        if self.unit_price is None:
            return 0
        return self.quantity * self.unit_price

    def save(self, *args, **kwargs):
        is_new = self._state.adding

        previous = None
        if not is_new and self.pk:
            previous = ServiceOperations.objects.filter(pk=self.pk).first()

        if self.product and not self.description:
            self.description = self.product.name

        if self.product and self.unit_price is None:
            self.unit_price = self.product.price or 0

        if self.unit_price is None:
            self.unit_price = 0

        with transaction.atomic():
            super().save(*args, **kwargs)

        service = self.service

        if is_new:
            create_stock_movement(service, self.product, self.quantity, 'out', 'parca kullanimi')
            return

        # ➜ update logic
        old_product = previous.product if previous else None
        old_qty = previous.quantity if previous else 0
        new_qty = self.quantity or 0

        if old_product != self.product:
            create_stock_movement(service, old_product, old_qty, 'return', 'urun degisikligi iade')
            create_stock_movement(service, self.product, new_qty, 'out', 'urun degisikligi kullanimi')
            return

        diff = new_qty - old_qty

        if diff > 0:
            create_stock_movement(service, self.product, diff, 'out', 'miktar artisi')
        elif diff < 0:
            create_stock_movement(service, self.product, abs(diff), 'return', 'miktar azalis')

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            if self.product and (self.quantity or 0) > 0:
                create_stock_movement(
                    self.service,
                    self.product,
                    self.quantity,
                    'return',
                    'islem iptali'
                )
            super().delete(*args, **kwargs)
    
    def __str__(self):
        return f"{self.name} ({self.quantity} x {self.unit_price})"

    class Meta:
        verbose_name = 'Servis İşlemi'
        verbose_name_plural = 'Servis İşlemleri'


class ServiceOperationTemplate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='service_operation_templates', null=True, blank=True)
    name = models.CharField(max_length=255, verbose_name='İşlem Adı')
    description = models.CharField(max_length=255, blank=True, default='', verbose_name='Açıklama')
    default_unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='Varsayılan Ücret')
    is_active = models.BooleanField(default=True, verbose_name='Aktif')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='service_operation_templates',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Servis İşlem Şablonu'
        verbose_name_plural = 'Servis İşlem Şablonları'
        ordering = ['name', '-created_at']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.default_unit_price} TL)"


class PaymentMethod(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='service_payment_methods', null=True, blank=True)
    name = models.CharField(max_length=20, verbose_name='Ödeme Yöntemi')
    bank_name = models.CharField(max_length=120, blank=True, null=True, verbose_name='Banka Adı')
    account_holder = models.CharField(max_length=120, blank=True, null=True, verbose_name='Hesap Sahibi')
    iban = models.CharField(max_length=34, blank=True, null=True, verbose_name='IBAN')
    is_default = models.BooleanField(default=False, verbose_name='Varsayılan Ödeme Yöntemi')

    def __str__(self):
        return self.name


def get_default_payment_type():
    payment_type = PaymentMethod.objects.filter(is_default=True).first()
    return payment_type.pk if payment_type else None


class ServicePayment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='service_payments', null=True, blank=True)
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='payments', verbose_name='Servis')
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Ödenen Tutar')
    payment_method = models.ForeignKey(PaymentMethod, on_delete=models.SET_NULL, null=True, default=get_default_payment_type, verbose_name='Ödeme Yöntemi')
    note = models.TextField(blank=True, null=True, verbose_name='Not')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Ödeme Tarihi')

    def __str__(self):
        payment_name = self.payment_method.name if self.payment_method else 'Belirtilmedi'
        return f"{self.service.receipt_number} - {self.amount} TL ({payment_name})"

    class Meta:
        verbose_name = 'Servis Ödemesi'
        verbose_name_plural = 'Servis Ödemeleri'

    def _transaction_receipt_ref(self):
        # Keep under accounting.Transaction.receipt_number max_length=50.
        return f"SP:{self.pk.hex}"

    def _resolve_account_type_from_payment_method(self):
        method_name = (self.payment_method.name if self.payment_method else '').lower()
        if any(token in method_name for token in ['kart', 'card', 'pos']):
            return 'credit_card'
        if any(token in method_name for token in ['banka', 'havale', 'eft', 'iban']):
            return 'bank'
        return 'cash'

    def _resolve_account(self):
        from accounting.models import Account

        account_type = self._resolve_account_type_from_payment_method()
        tenant = getattr(getattr(self.service, "customer", None), "tenant", None)
        account_qs = Account.objects.filter(account_type=account_type)
        if tenant:
            account_qs = account_qs.filter(tenant=tenant)
        account = account_qs.order_by('created_at').first()
        if account:
            return account

        defaults = {
            'cash': 'Ana Kasa',
            'bank': 'Ana Banka Hesabı',
            'credit_card': 'Ana POS Hesabı',
            'other': 'Diğer Hesap',
        }
        return Account.objects.create(
            tenant=tenant,
            name=defaults.get(account_type, 'Ana Hesap'),
            account_type=account_type,
            balance=Decimal('0.00'),
        )

    def _sync_income_transaction(self):
        from accounting.models import Transaction

        if not self.pk:
            return

        tenant = getattr(getattr(self.service, "customer", None), "tenant", None)
        account = self._resolve_account()
        receipt_ref = self._transaction_receipt_ref()
        receipt_number = Transaction.normalize_receipt_number(receipt_ref)
        base_description = f"Servis tahsilati #{self.service.receipt_number}"
        if self.note:
            base_description = f"{base_description} | Not: {self.note}"

        existing = Transaction.objects.filter(
            receipt_number=receipt_number,
            transaction_type='income',
        ).order_by('-created_at').first()

        if existing:
            existing.tenant = tenant
            existing.account = account
            existing.amount = self.amount
            existing.date = timezone.now()
            existing.description = base_description
            existing.service = self.service
            existing.save()
            return

        Transaction.objects.create(
            tenant=tenant,
            transaction_type='income',
            account=account,
            amount=self.amount,
            date=timezone.now(),
            description=base_description,
            receipt_number=receipt_number,
            service=self.service,
        )

    def save(self, *args, **kwargs):
        # Atomic write: if any post_save side effect fails, payment row should
        # not remain persisted alone.
        with transaction.atomic():
            super().save(*args, **kwargs)
            self._sync_income_transaction()

    def delete(self, *args, **kwargs):
        from accounting.models import Transaction

        with transaction.atomic():
            tenant = getattr(getattr(self.service, "customer", None), "tenant", None)
            receipt_ref = self._transaction_receipt_ref()
            receipt_number = Transaction.normalize_receipt_number(receipt_ref)
            income_tx = Transaction.objects.filter(
                receipt_number=receipt_number,
                transaction_type='income',
            ).order_by('-created_at').first()

            if income_tx:
                reversal_note = (
                    f"Servis odeme IPTAL (ters kayit) #{self.service.receipt_number} | "
                    f"Silinen odeme: {self.amount}"
                )
                if self.note:
                    reversal_note = f"{reversal_note} | Not: {self.note}"

                Transaction.objects.create(
                    tenant=tenant,
                    transaction_type='expense',
                    account=income_tx.account,
                    amount=income_tx.amount,
                    date=timezone.now(),
                    description=reversal_note,
                    receipt_number=Transaction.normalize_receipt_number(f"{receipt_ref}:REV:{uuid.uuid4().hex[:8]}"),
                    service=self.service,
                )

            super().delete(*args, **kwargs)

class ServiceTimeline(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='service_timelines', null=True, blank=True)
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='timeline', verbose_name='Servis')
    old_status = models.CharField(max_length=20, verbose_name='Eski Durum')
    new_status = models.CharField(max_length=20, verbose_name='Yeni Durum')
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='İşlem Tarihi')

    class Meta:
        verbose_name = 'Servis Zaman Çizelgesi'
        verbose_name_plural = 'Servis Zaman Çizelgeleri'
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.service.receipt_number} - {self.timestamp}"

class ServicePhoto(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='service_photos', null=True, blank=True)
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='photos', verbose_name='Servis')
    image = models.ImageField(upload_to=tenant_directory_path, verbose_name='Fotoğraf')
    description = models.CharField(max_length=255, blank=True, null=True, verbose_name='Açıklama')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Servis Fotoğrafı'
        verbose_name_plural = 'Servis Fotoğrafları'

    def save(self, *args, **kwargs):
        if self.id:
            try:
                existing_instance = ServicePhoto.objects.get(id=self.id)
                if self.image and existing_instance.image != self.image:
                    self.image = process_image(self.image)
            except ServicePhoto.DoesNotExist:
                if self.image:
                    self.image = process_image(self.image)
        else:
            if self.image:
                self.image = process_image(self.image)

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.service.receipt_number} - Fotoğraf"


@receiver(pre_delete, sender=Technician)
def reassign_services_on_technician_delete(sender, instance, **kwargs):
    admin_tech = Technician.objects.filter(user__is_staff=True, user__is_active=True).first()
    if admin_tech and admin_tech != instance:
        Service.objects.filter(technician=instance).update(technician=admin_tech)
    else:
        Service.objects.filter(technician=instance).update(technician=None)
