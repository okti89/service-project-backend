from rest_framework import serializers
from decimal import Decimal
from django.db.models import Q, Sum
from .models import (
    DeviceType, Brand, Model, Service, ServiceStatus,
    ServiceOperations, ServiceSignature, PaymentMethod, ServicePayment, 
    ServiceTimeline, ServicePhoto, WarrantyCertificate, ServiceOperationTemplate
)

SERVICE_STATUS_META = {
    'new': {'label': 'Yeni', 'color': '#16A34A'},
    'assigned': {'label': 'Beklemede', 'color': '#2563EB'},
    'in_progress': {'label': 'Devam Ediyor', 'color': '#F59E0B'},
    'postponed': {'label': 'Ertelendi', 'color': '#7C3AED'},
    'completed': {'label': 'Tamamlandi', 'color': '#16A34A'},
    'cancelled': {'label': 'Iptal Edildi', 'color': '#DC2626'},
}


def get_service_status_label(status_code):
    if isinstance(status_code, ServiceStatus):
        return status_code.name
    meta = SERVICE_STATUS_META.get(status_code or '')
    if meta:
        return meta['label']
    return str(status_code or '-')


def get_service_status_color(status_code):
    if isinstance(status_code, ServiceStatus):
        return status_code.color
    meta = SERVICE_STATUS_META.get(status_code or '')
    if meta:
        return meta['color']
    return '#6B7280'
# === Core Definitions Seializers ===
class DeviceTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceType
        fields = '__all__'

class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = '__all__'

class ModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Model
        fields = '__all__'

class PaymentMethodSerializer(serializers.ModelSerializer):
    def validate_iban(self, value):
        raw = str(value or '').replace(' ', '').upper()
        if not raw:
            return None
        if len(raw) < 15 or len(raw) > 34:
            raise serializers.ValidationError('Gecerli bir IBAN girin.')
        if not raw[:2].isalpha() or not raw[2:].isalnum():
            raise serializers.ValidationError('Gecerli bir IBAN girin.')
        return raw

    class Meta:
        model = PaymentMethod
        fields = '__all__'


class ServiceStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceStatus
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']


class ServiceOperationTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceOperationTemplate
        fields = '__all__'
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

# === Relational Service Components ===
class ServiceOperationsSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    
    class Meta:
        model = ServiceOperations
        fields = ['id', 'service', 'name', 'product', 'product_name', 'description', 'quantity', 'unit_price', 'total_price']
        read_only_fields = ['id', 'total_price']

    def validate_service(self, value):
        request = self.context.get('request')
        tenant = getattr(getattr(request, 'user', None), 'tenant', None)
        if value and getattr(getattr(value, 'customer', None), 'tenant', None) != tenant:
            raise serializers.ValidationError('Bu servis baska bir tenant kaydina ait.')
        return value

class ServicePaymentSerializer(serializers.ModelSerializer):
    payment_method_name = serializers.CharField(source='payment_method.name', read_only=True)
    payment_method_iban = serializers.CharField(source='payment_method.iban', read_only=True)
    payment_method_bank_name = serializers.CharField(source='payment_method.bank_name', read_only=True)
    payment_method_account_holder = serializers.CharField(source='payment_method.account_holder', read_only=True)
    
    class Meta:
        model = ServicePayment
        fields = [
            'id',
            'service',
            'amount',
            'payment_method',
            'payment_method_name',
            'payment_method_iban',
            'payment_method_bank_name',
            'payment_method_account_holder',
            'note',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def validate_service(self, value):
        request = self.context.get('request')
        tenant = getattr(getattr(request, 'user', None), 'tenant', None)
        if value and getattr(getattr(value, 'customer', None), 'tenant', None) != tenant:
            raise serializers.ValidationError('Bu servis baska bir tenant kaydina ait.')
        return value

    def validate(self, attrs):
        instance = getattr(self, 'instance', None)
        service = attrs.get('service') or getattr(instance, 'service', None)
        payment_method = attrs.get('payment_method') or getattr(instance, 'payment_method', None)
        amount = attrs.get('amount', getattr(instance, 'amount', None))
        tenant = getattr(getattr(self.context.get('request'), 'user', None), 'tenant', None)

        if amount is None:
            return attrs

        amount = Decimal(str(amount))
        if amount <= 0:
            raise serializers.ValidationError({'amount': 'Odeme tutari sifirdan buyuk olmali.'})

        if not service:
            return attrs
        if payment_method and getattr(payment_method, 'tenant', None) != tenant:
            raise serializers.ValidationError({'payment_method': 'Odeme yontemi baska bir tenant kaydina ait.'})

        service_total = Decimal('0.00')
        for item in service.items.all():
            line_total = item.total_price or 0
            service_total += Decimal(str(line_total))

        paid_qs = service.payments.all()
        if instance and instance.pk:
            paid_qs = paid_qs.exclude(pk=instance.pk)
        paid_total = Decimal(str(paid_qs.aggregate(total=Sum('amount')).get('total') or 0))

        if service_total <= 0:
            raise serializers.ValidationError({'amount': 'Servis toplam tutari sifir oldugu icin odeme eklenemez.'})

        return attrs

class ServiceSignatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceSignature
        fields = ['id', 'service', 'customer_signature', 'technician_signature', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

class ServiceTimelineSerializer(serializers.ModelSerializer):
    old_status_name = serializers.SerializerMethodField()
    new_status_name = serializers.SerializerMethodField()
    new_status_color = serializers.SerializerMethodField()
    
    class Meta:
        model = ServiceTimeline
        fields = ['id', 'service', 'old_status', 'old_status_name', 'new_status', 'new_status_name', 'new_status_color', 'timestamp']
        read_only_fields = ['id', 'timestamp']

    def get_old_status_name(self, obj):
        return get_service_status_label(obj.old_status)

    def get_new_status_name(self, obj):
        return get_service_status_label(obj.new_status)

    def get_new_status_color(self, obj):
        return get_service_status_color(obj.new_status)

class ServicePhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServicePhoto
        fields = ['id', 'service', 'image', 'description', 'created_at']
        read_only_fields = ['id', 'created_at']

class WarrantyCertificateSerializer(serializers.ModelSerializer):
    service_receipt_number = serializers.CharField(source='service.receipt_number', read_only=True)
    service_customer_name = serializers.CharField(source='service.customer_full_name', read_only=True)

    class Meta:
        model = WarrantyCertificate
        fields = [
            'id',
            'service',
            'service_receipt_number',
            'service_customer_name',
            'certificate_no',
            'warranty_months',
            'coverage_details',
            'start_date',
            'end_date',
            'status',
            'issued_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'certificate_no', 'end_date', 'issued_at', 'updated_at']

class PublicServiceTimelineSerializer(serializers.ModelSerializer):
    old_status_name = serializers.SerializerMethodField()
    new_status_name = serializers.SerializerMethodField()
    new_status_color = serializers.SerializerMethodField()

    class Meta:
        model = ServiceTimeline
        fields = ['id', 'old_status_name', 'new_status_name', 'new_status_color', 'timestamp']

    def get_old_status_name(self, obj):
        return get_service_status_label(obj.old_status)

    def get_new_status_name(self, obj):
        return get_service_status_label(obj.new_status)

    def get_new_status_color(self, obj):
        return get_service_status_color(obj.new_status)

class PublicServiceOperationsSerializer(serializers.ModelSerializer):
    operation_name = serializers.CharField(source='product.name', read_only=True)
    custom_name = serializers.CharField(source='name', read_only=True)
    price = serializers.DecimalField(source='unit_price', max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = ServiceOperations
        fields = ['id', 'operation_name', 'custom_name', 'price', 'quantity']

class PublicServiceSerializer(serializers.ModelSerializer):
    status_name = serializers.SerializerMethodField()
    status_color = serializers.SerializerMethodField()
    timeline = PublicServiceTimelineSerializer(many=True, read_only=True)
    items = PublicServiceOperationsSerializer(many=True, read_only=True)
    
    # Public tracking page shows the customer name in full.
    masked_customer_name = serializers.SerializerMethodField()
    
    total_paid = serializers.SerializerMethodField()
    total_price = serializers.SerializerMethodField()

    device_type_name = serializers.CharField(source='device_type.name', read_only=True)
    device_brand_name = serializers.CharField(source='device_brand.name', read_only=True)
    device_model_name = serializers.CharField(source='device_model.name', read_only=True)

    class Meta:
        model = Service
        fields = [
            'id', 'receipt_number', 'masked_customer_name',
            'device_type', 'device_brand', 'device_model', 
            'device_type_name', 'device_brand_name', 'device_model_name',
            'fault_description', 'status_name', 'status_color', 'created_at', 'updated_at',
            'timeline', 'items', 'total_paid', 'total_price',
        ]

    def get_masked_customer_name(self, obj):
        name = obj.customer_full_name
        if not name and obj.customer:
            name = obj.customer.full_name
        return name or "MÃ¼ÅŸteri"
    def get_total_paid(self, obj):
        return sum(p.amount for p in obj.payments.all())

    def get_total_price(self, obj):
        return sum(item.unit_price * item.quantity for item in obj.items.all())

    def get_status_name(self, obj):
        return get_service_status_label(obj.service_status)

    def get_status_color(self, obj):
        return get_service_status_color(obj.service_status)


# === Primary Service Serializer ===
class ServiceSerializer(serializers.ModelSerializer):
    service_status = serializers.CharField(required=False)
    device_type_name = serializers.CharField(source='device_type', read_only=True)
    device_brand_name = serializers.CharField(source='device_brand', read_only=True)
    device_model_name = serializers.CharField(source='device_model', read_only=True)
    technician_name = serializers.CharField(source='technician.user.get_full_name', read_only=True)
    technician_avatar = serializers.SerializerMethodField()
    # Inline sub-relations
    items = ServiceOperationsSerializer(many=True, read_only=True)
    payments = ServicePaymentSerializer(many=True, read_only=True)
    photos = ServicePhotoSerializer(many=True, read_only=True)
    timeline = ServiceTimelineSerializer(many=True, read_only=True)
    warranty_certificate = WarrantyCertificateSerializer(read_only=True)
    signatures = ServiceSignatureSerializer(many=True, read_only=True)
    total_price = serializers.SerializerMethodField()
    total_paid = serializers.SerializerMethodField()
    remaining_balance = serializers.SerializerMethodField()
    status_name = serializers.SerializerMethodField()
    status_color = serializers.SerializerMethodField()
    class Meta:
        model = Service
        fields = [
            'id', 'customer', 'customer_phone', 'customer_full_name', 'customer_address',
            'fault_description', 'device_type', 'device_type_name', 'device_brand', 'device_brand_name',
            'device_model', 'device_model_name', 'technician', 'technician_name',
            'service_status', 'status_name', 'status_color', 'receipt_number',
            'scheduled_date', 'technician_avatar',
            'created_at', 'updated_at',
            'items', 'payments', 'photos', 'timeline', 'warranty_certificate', 'signatures',
            'total_price', 'total_paid', 'remaining_balance'
        ]
        read_only_fields = ['id', 'receipt_number', 'created_at', 'updated_at']

    def get_technician_avatar(self, obj):
        avatar = getattr(getattr(getattr(obj, 'technician', None), 'user', None), 'avatar', None)
        if not avatar:
            return None

        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(avatar.url)
        return avatar.url

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get('request')
        tenant = getattr(getattr(request, 'user', None), 'tenant', None)
        instance = getattr(self, 'instance', None)

        customer = attrs.get('customer') or getattr(instance, 'customer', None)
        technician = attrs.get('technician') or getattr(instance, 'technician', None)

        if customer and getattr(customer, 'tenant', None) != tenant:
            raise serializers.ValidationError({'customer': 'Secilen musteri baska bir tenant kaydina ait.'})

        if technician and getattr(getattr(technician, 'user', None), 'tenant', None) != tenant:
            raise serializers.ValidationError({'technician': 'Secilen teknisyen baska bir tenant kaydina ait.'})

        device_type = attrs.get('device_type') or getattr(instance, 'device_type', None)
        device_brand = attrs.get('device_brand') or getattr(instance, 'device_brand', None)
        device_model = attrs.get('device_model') or getattr(instance, 'device_model', None)

        if device_type and getattr(device_type, 'tenant', None) != tenant:
            raise serializers.ValidationError({'device_type': 'Secilen cihaz turu baska bir tenant kaydina ait.'})
        if device_brand and getattr(device_brand, 'tenant', None) != tenant:
            raise serializers.ValidationError({'device_brand': 'Secilen marka baska bir tenant kaydina ait.'})
        if device_model and getattr(device_model, 'tenant', None) != tenant:
            raise serializers.ValidationError({'device_model': 'Secilen model baska bir tenant kaydina ait.'})

        return attrs

    def validate_service_status(self, value):
        value = str(value or '').strip() or 'new'
        request = self.context.get('request')
        tenant = getattr(getattr(request, 'user', None), 'tenant', None)
        exists = ServiceStatus.objects.filter(code=value, is_active=True).filter(
            Q(tenant=tenant) | Q(tenant__isnull=True)
        ).exists()
        if not exists and value not in SERVICE_STATUS_META:
            raise serializers.ValidationError('Gecersiz servis durumu.')
        return value

    def create(self, validated_data):
        status_code = validated_data.pop('service_status', None)
        instance = Service(**validated_data)
        if status_code:
            instance.service_status = status_code
        instance.save()
        return instance

    def update(self, instance, validated_data):
        status_code = validated_data.pop('service_status', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if status_code is not None:
            instance.service_status = status_code
        instance.save()
        return instance

    def get_total_price(self, obj):
        total = Decimal('0.00')
        for item in obj.items.all():
            total += Decimal(str(item.total_price or 0))
        return total

    def get_total_paid(self, obj):
        return Decimal(str(obj.payments.aggregate(total=Sum('amount')).get('total') or 0))

    def get_remaining_balance(self, obj):
        remaining = self.get_total_price(obj) - self.get_total_paid(obj)
        if remaining < 0:
            return Decimal('0.00')
        return remaining

    def get_status_name(self, obj):
        return get_service_status_label(obj.service_status)

    def get_status_color(self, obj):
        return get_service_status_color(obj.service_status)




