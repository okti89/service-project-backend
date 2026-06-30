from django.contrib import admin
from .models import CompanyConfig, WorkingHour, HolidayException


@admin.register(CompanyConfig)
class CompanyConfigAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'phone_number', 'email', 'updated_at')
    list_filter = ('tenant',)
    search_fields = ('name', 'phone_number', 'email')


@admin.register(WorkingHour)
class WorkingHourAdmin(admin.ModelAdmin):
    list_display = ('company', 'day_of_week', 'start_time', 'end_time', 'is_holiday')
    list_filter = ('company__tenant', 'day_of_week', 'is_holiday')
    search_fields = ('company__name',)


@admin.register(HolidayException)
class HolidayExceptionAdmin(admin.ModelAdmin):
    list_display = ('title', 'company', 'start_date', 'end_date', 'is_half_day')
    list_filter = ('company__tenant', 'is_half_day', 'start_date')
    search_fields = ('title', 'company__name')
