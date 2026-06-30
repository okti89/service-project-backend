from django.contrib import admin
from .models import TechnicianCompensation, Payroll, PayrollComponent, PayrollTemplate


@admin.register(PayrollTemplate)
class PayrollTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'type', 'default_amount', 'is_active')
    list_filter = ('tenant', 'type', 'is_active')
    search_fields = ('name',)


@admin.register(PayrollComponent)
class PayrollComponentAdmin(admin.ModelAdmin):
    list_display = ('payroll', 'name', 'type', 'amount', 'is_manual')
    list_filter = ('payroll__technician__user__tenant', 'type', 'is_manual')
    search_fields = ('name',)


@admin.register(Payroll)
class PayrollAdmin(admin.ModelAdmin):
    list_display = ('technician', 'period_start', 'period_end', 'base_salary', 'total_premiums', 'total_deductions', 'net_salary', 'status')
    list_filter = ('technician__user__tenant', 'period_start', 'status')
    search_fields = ('technician__user__first_name', 'technician__user__last_name', 'technician__user__email')


@admin.register(TechnicianCompensation)
class TechnicianCompensationAdmin(admin.ModelAdmin):
    list_display = ('technician', 'base_salary', 'salary_type', 'iban', 'sgk_number')
    list_filter = ('technician__user__tenant', 'salary_type',)
    search_fields = ('technician__user__first_name', 'technician__user__last_name', 'technician__user__email')
