from django.contrib import admin

from core.admin import TurkishAdminMixin
from .models import (
    Brand,
    DeviceType,
    Model,
    PaymentMethod,
    Service,
    ServiceOperations,
    ServiceSignature,
    ServicePayment,
    ServicePhoto,
    ServiceStatus,
    ServiceTimeline,
    ServiceOperationTemplate,
    WarrantyCertificate,
)

@admin.register(Service)
class ServiceAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {"tenant": "Firma", "receipt_number": "Servis Numarası"}
    list_display = (
        'receipt_number',
        'customer_full_name',
        'technician',
        'status',
        'scheduled_date',
        'updated_at',
    )
    list_filter = ('customer__tenant', 'status', 'scheduled_date')
    search_fields = ('receipt_number', 'customer_full_name', 'customer_phone', 'device_brand__name', 'device_model__name')
    readonly_fields = ('receipt_number', 'created_at', 'updated_at')
    autocomplete_fields = ('customer', 'technician', 'status', 'device_type', 'device_brand', 'device_model')
    date_hierarchy = 'scheduled_date'
    list_select_related = ('customer', 'technician', 'status')


@admin.register(ServiceStatus)
class ServiceStatusAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name_plural = 'Servis Durumları'
    admin_field_labels = {
        'name': 'Durum Adı', 'code': 'Kod', 'tenant': 'Firma', 'color': 'Renk', 'sort_order': 'Sıra',
        'is_default': 'Varsayılan', 'is_terminal': 'Son Durum', 'is_active': 'Aktif',
    }
    list_display = ('name', 'code', 'tenant', 'color', 'sort_order', 'is_default', 'is_terminal', 'is_active')
    list_filter = ('tenant', 'is_active', 'is_default', 'is_terminal')
    search_fields = ('name', 'code')

@admin.register(ServiceSignature)
class ServiceSignatureAdmin(TurkishAdminMixin, admin.ModelAdmin):
    list_display = ('service', 'created_at')
    list_filter = ('service__customer__tenant', 'created_at')
    search_fields = ('service__receipt_number',)
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('service',)

@admin.register(ServicePayment)
class ServicePaymentAdmin(TurkishAdminMixin, admin.ModelAdmin):
    list_display = ('service', 'amount', 'payment_method', 'created_at')
    list_filter = ('service__customer__tenant', 'payment_method', 'created_at')
    search_fields = ('service__receipt_number', 'service__customer_full_name')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('service', 'payment_method')


@admin.register(ServiceTimeline)
class ServiceTimelineAdmin(TurkishAdminMixin, admin.ModelAdmin):
    list_display = ('service', 'old_status', 'new_status', 'timestamp')
    list_filter = ('service__customer__tenant', 'old_status', 'new_status', 'timestamp')
    search_fields = ('service__receipt_number',)
    readonly_fields = ('timestamp',)
    autocomplete_fields = ('service',)


@admin.register(ServicePhoto)
class ServicePhotoAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {'created_at': 'Oluşturulma Tarihi'}
    list_display = ('service', 'description', 'created_at')
    list_filter = ('service__customer__tenant', 'created_at')
    search_fields = ('service__receipt_number', 'description')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('service',)


@admin.register(WarrantyCertificate)
class WarrantyCertificateAdmin(TurkishAdminMixin, admin.ModelAdmin):
    list_display = ('certificate_no', 'service', 'start_date', 'end_date', 'status')
    list_filter = ('service__customer__tenant', 'status', 'start_date', 'end_date')
    search_fields = ('certificate_no', 'service__receipt_number', 'service__customer_full_name')
    readonly_fields = ('certificate_no', 'issued_at', 'updated_at')
    autocomplete_fields = ('service',)


@admin.register(ServiceOperations)
class ServiceOperationsAdmin(TurkishAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'service', 'product', 'quantity', 'unit_price')
    list_filter = ('service__customer__tenant',)
    search_fields = ('name', 'description', 'service__receipt_number', 'product__name')
    autocomplete_fields = ('service', 'product')


@admin.register(ServiceOperationTemplate)
class ServiceOperationTemplateAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {'tenant': 'Firma', 'created_by': 'Oluşturan', 'updated_at': 'Güncellenme Tarihi'}
    list_display = ('name', 'default_unit_price', 'is_active', 'created_by', 'updated_at')
    list_filter = ('tenant', 'is_active')
    search_fields = ('name', 'description')



@admin.register(PaymentMethod)
class PaymentMethodAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name = 'Ödeme Yöntemi'
    admin_verbose_name_plural = 'Ödeme Yöntemleri'
    admin_field_labels = {'tenant': 'Firma'}
    list_display = ('name', 'tenant', 'bank_name', 'account_holder', 'iban', 'is_default')
    list_filter = ('tenant', 'is_default')
    search_fields = ('name', 'bank_name', 'account_holder', 'iban')


@admin.register(Brand)
class BrandAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {'tenant': 'Firma'}
    list_display = ('name', 'tenant')
    list_filter = ('tenant',)
    search_fields = ('name',)


@admin.register(DeviceType)
class DeviceTypeAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {'name': 'Cihaz Türü', 'tenant': 'Firma'}
    list_display = ('name', 'tenant')
    list_filter = ('tenant',)
    search_fields = ('name',)


@admin.register(Model)
class ModelAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {'tenant': 'Firma'}
    list_display = ('name', 'brand', 'tenant')
    list_filter = ('tenant', 'brand')
    search_fields = ('name', 'brand__name')
    autocomplete_fields = ('brand',)
