from django.contrib import admin

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
class ServiceAdmin(admin.ModelAdmin):
    list_display = (
        'receipt_number',
        'customer_full_name',
        'technician',
        'status',
        'scheduled_date',
        'updated_at',
    )
    list_filter = ('customer__tenant', 'status', 'scheduled_date')
    search_fields = ('receipt_number', 'customer_full_name', 'customer_phone', 'device_brand', 'device_model')
    readonly_fields = ('receipt_number', 'created_at', 'updated_at')
    autocomplete_fields = ('customer',)


@admin.register(ServiceStatus)
class ServiceStatusAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'tenant', 'color', 'sort_order', 'is_default', 'is_terminal', 'is_active')
    list_filter = ('tenant', 'is_active', 'is_default', 'is_terminal')
    search_fields = ('name', 'code')

@admin.register(ServiceSignature)
class ServiceSignatureAdmin(admin.ModelAdmin):
    list_display = ('service', 'created_at')
    list_filter = ('service__customer__tenant', 'created_at')
    search_fields = ('service__receipt_number',)
    readonly_fields = ('created_at',)
    autocomplete_fields = ('service',)

@admin.register(ServicePayment)
class ServicePaymentAdmin(admin.ModelAdmin):
    list_display = ('service', 'amount', 'payment_method', 'created_at')
    list_filter = ('service__customer__tenant', 'payment_method', 'created_at')
    search_fields = ('service__receipt_number', 'service__customer_full_name')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('service', 'payment_method')


@admin.register(ServiceTimeline)
class ServiceTimelineAdmin(admin.ModelAdmin):
    list_display = ('service', 'old_status', 'new_status', 'timestamp')
    list_filter = ('service__customer__tenant', 'old_status', 'new_status', 'timestamp')
    search_fields = ('service__receipt_number',)
    readonly_fields = ('timestamp',)
    autocomplete_fields = ('service',)


@admin.register(ServicePhoto)
class ServicePhotoAdmin(admin.ModelAdmin):
    list_display = ('service', 'description', 'created_at')
    list_filter = ('service__customer__tenant', 'created_at')
    search_fields = ('service__receipt_number', 'description')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('service',)


@admin.register(WarrantyCertificate)
class WarrantyCertificateAdmin(admin.ModelAdmin):
    list_display = ('service', 'start_date', 'end_date', 'status')
    list_filter = ('service__customer__tenant', 'status', 'start_date', 'end_date')
    search_fields = ('service__receipt_number',)
    readonly_fields = ('start_date', 'end_date', 'issued_at', 'updated_at')
    autocomplete_fields = ('service',)


@admin.register(ServiceOperations)
class ServiceOperationsAdmin(admin.ModelAdmin):
    list_display = ('name', 'unit_price')
    list_filter = ('service__customer__tenant',)
    search_fields = ('name',)


@admin.register(ServiceOperationTemplate)
class ServiceOperationTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'default_unit_price', 'is_active', 'created_by', 'updated_at')
    list_filter = ('tenant', 'is_active')
    search_fields = ('name', 'description')



@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'bank_name', 'account_holder', 'iban', 'is_default')
    list_filter = ('tenant', 'is_default')
    search_fields = ('name', 'bank_name', 'account_holder', 'iban')


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant')
    list_filter = ('tenant',)
    search_fields = ('name',)


@admin.register(DeviceType)
class DeviceTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant')
    list_filter = ('tenant',)
    search_fields = ('name',)


@admin.register(Model)
class ModelAdmin(admin.ModelAdmin):
    list_display = ('name', 'brand', 'tenant')
    list_filter = ('tenant', 'brand')
    search_fields = ('name', 'brand__name')
    autocomplete_fields = ('brand',)
