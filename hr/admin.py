from django.contrib import admin

from core.admin import TurkishAdminMixin
from .models import TechnicianCompensation, Payroll, PayrollComponent, PayrollTemplate


@admin.register(PayrollTemplate)
class PayrollTemplateAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name = "Bordro Şablonu"
    admin_verbose_name_plural = "Bordro Şablonları"
    admin_field_labels = {"name": "Ad", "tenant": "Firma", "type": "Tür", "default_amount": "Varsayılan Tutar", "is_active": "Aktif"}
    list_display = ('name', 'tenant', 'type', 'default_amount', 'is_active')
    list_filter = ('tenant', 'type', 'is_active')
    search_fields = ('name',)


@admin.register(PayrollComponent)
class PayrollComponentAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name = "Bordro Kalemi"
    admin_verbose_name_plural = "Bordro Kalemleri"
    admin_field_labels = {"payroll": "Bordro", "name": "Ad", "type": "Tür", "amount": "Tutar", "is_manual": "Elle Eklendi"}
    list_display = ('payroll', 'name', 'type', 'amount', 'is_manual')
    list_filter = ('payroll__technician__user__tenant', 'type', 'is_manual')
    search_fields = ('name',)


@admin.register(Payroll)
class PayrollAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name = "Bordro"
    admin_verbose_name_plural = "Bordrolar"
    admin_field_labels = {
        "technician": "Teknisyen", "period_start": "Dönem Başlangıcı", "period_end": "Dönem Sonu",
        "base_salary": "Temel Maaş", "total_premiums": "Toplam Prim", "total_deductions": "Toplam Kesinti",
        "net_salary": "Net Maaş", "status": "Durum", "paid_date": "Ödeme Tarihi",
    }
    list_display = ('technician', 'period_start', 'period_end', 'base_salary', 'total_premiums', 'total_deductions', 'net_salary', 'status')
    list_filter = ('technician__user__tenant', 'period_start', 'status')
    search_fields = ('technician__user__first_name', 'technician__user__last_name', 'technician__user__email')
    date_hierarchy = 'period_start'


@admin.register(TechnicianCompensation)
class TechnicianCompensationAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {"technician": "Teknisyen", "base_salary": "Temel Maaş", "salary_type": "Maaş Türü", "iban": "IBAN", "sgk_number": "SGK Numarası"}
    list_display = ('technician', 'base_salary', 'salary_type', 'iban', 'sgk_number')
    list_filter = ('technician__user__tenant', 'salary_type',)
    search_fields = ('technician__user__first_name', 'technician__user__last_name', 'technician__user__email')
