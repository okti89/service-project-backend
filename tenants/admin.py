from django.contrib import admin
from django import forms
from django.utils import timezone

from core.admin import TurkishAdminMixin
from .models import Tenant, TenantMembership


class TenantMembershipAdminForm(forms.ModelForm):
    class Meta:
        model = TenantMembership
        fields = ('tenant', 'plan', 'premium_started_at', 'renewal_date')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields['premium_started_at'].initial = timezone.localdate()
        self.fields['premium_started_at'].label = 'Üyelik Başlangıç Tarihi'
        self.fields['renewal_date'].label = 'Bitiş Tarihi'
        self.fields['renewal_date'].help_text = 'Boş bırakılırsa Deneme için 5 gün, Premium için 1 yıl sonrası otomatik hesaplanır.'

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('premium_started_at')
        end = cleaned_data.get('renewal_date')
        if start and end and end <= start:
            self.add_error('renewal_date', 'Yenileme tarihi başlangıç tarihinden sonra olmalıdır.')
        return cleaned_data


@admin.register(Tenant)
class TenantAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name = "Firma"
    admin_verbose_name_plural = "Firmalar"
    admin_field_labels = {
        "name": "Firma Adı", "code": "Firma Kodu", "app_name": "Uygulama Adı", "features": "Özellikler",
        "is_active": "Aktif", "created_at": "Oluşturulma Tarihi", "updated_at": "Güncellenme Tarihi",
    }
    list_display = ("name", "code", "app_name", "is_active", "created_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "code", "app_name")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("name",)


@admin.register(TenantMembership)
class TenantMembershipAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name = "Firma Üyeliği"
    admin_verbose_name_plural = "Firma Üyelikleri"
    admin_field_labels = {
        "tenant": "Firma", "plan": "Plan", "period_number": "Dönem Numarası",
        "premium_started_at": "Üyelik Başlangıç Tarihi", "renewal_date": "Bitiş Tarihi", "created_at": "Oluşturulma Tarihi",
    }
    list_display = ('tenant', 'plan', 'period_number', 'premium_started_at', 'renewal_date', 'created_at')
    list_filter = ('plan', 'tenant')
    search_fields = ('tenant__name', 'tenant__code')
    form = TenantMembershipAdminForm
    fields = ('tenant', 'plan', 'premium_started_at', 'renewal_date', 'period_number', 'created_at')
    readonly_fields = ('period_number', 'created_at')
    actions = ('renew_selected_memberships',)

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = super().get_readonly_fields(request, obj)
        return (*readonly_fields, 'tenant') if obj else readonly_fields

    @admin.action(description='Seçili üyelikleri bir yıl yenile')
    def renew_selected_memberships(self, request, queryset):
        renewed = 0
        for membership in queryset:
            latest = membership.tenant.memberships.order_by('-period_number').first()
            if latest and latest.id == membership.id:
                membership.renew()
                renewed += 1
        self.message_user(request, f'{renewed} üyelik dönemi yenilendi.')
