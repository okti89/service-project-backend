from django.contrib import admin

from core.admin import TurkishAdminMixin
from .models import CompanyConfig, WorkingHour, HolidayException


@admin.register(CompanyConfig)
class CompanyConfigAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {
        "tenant": "Firma", "name": "Firma Adı", "panel_url": "Panel Adresi", "logo": "Logo",
        "phone_number": "Telefon", "email": "E-posta", "address": "Adres", "max_users": "Azami Kullanıcı",
        "force_update": "Güncellemeyi Zorunlu Tut", "created_at": "Oluşturulma Tarihi", "updated_at": "Güncellenme Tarihi",
    }
    list_display = ('name', 'tenant', 'phone_number', 'email', 'updated_at')
    list_filter = ('tenant',)
    search_fields = ('name', 'phone_number', 'email')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(WorkingHour)
class WorkingHourAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {"tenant": "Firma", "company": "Şirket"}
    list_display = ('company', 'day_of_week', 'start_time', 'end_time', 'is_holiday')
    list_filter = ('company__tenant', 'day_of_week', 'is_holiday')
    search_fields = ('company__name',)


@admin.register(HolidayException)
class HolidayExceptionAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {"tenant": "Firma", "company": "Şirket", "created_at": "Oluşturulma Tarihi", "updated_at": "Güncellenme Tarihi"}
    list_display = ('title', 'company', 'start_date', 'end_date', 'is_half_day')
    list_filter = ('company__tenant', 'is_half_day', 'start_date')
    search_fields = ('title', 'company__name')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'start_date'
