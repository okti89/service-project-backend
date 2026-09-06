from django.contrib import admin

from core.admin import TurkishAdminMixin
from .models import (
    LocationLog,
    Technician,
    TechnicianAttendance,
    TechnicianLocation,
    TechnicianPermissions,
    TechnicianShift,
    TechnicianStatus,
)


@admin.register(TechnicianStatus)
class TechnicianStatusAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name = "Teknisyen Durumu"
    admin_verbose_name_plural = "Teknisyen Durumları"
    admin_field_labels = {"name": "Durum Adı", "color": "Renk", "tenant": "Firma"}
    list_display = ("name", "color", "tenant")
    list_filter = ("tenant",)
    search_fields = ("name",)


@admin.register(Technician)
class TechnicianAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {"user": "Kullanıcı", "tenant": "Firma"}
    list_display = ("user", "tenant", "status", "is_online", "hire_date", "last_online")
    list_filter = ("tenant", "is_online", "status")
    search_fields = ("user__email", "user__first_name", "user__last_name", "user__phone_number")
    readonly_fields = ("id", "created_at", "updated_at")
    autocomplete_fields = ("user",)


@admin.register(TechnicianLocation)
class TechnicianLocationAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {"technician": "Teknisyen", "tenant": "Firma"}
    list_display = ("technician", "location", "latitude", "longitude", "updated_at")
    list_filter = ("tenant",)
    search_fields = ("technician__email", "location")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("technician",)


@admin.register(TechnicianPermissions)
class TechnicianPermissionsAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {"technician": "Teknisyen", "tenant": "Firma"}
    list_display = ("technician", "tenant", "can_manage_customers", "can_manage_inventory", "can_manage_services")
    list_filter = ("tenant", "can_manage_customers", "can_manage_inventory", "can_manage_users",
                   "can_manage_accounting", "can_manage_notifications", "can_manage_hr",
                   "can_manage_reports", "can_manage_settings", "can_manage_services",
                   "can_use_global_search", "can_manage_technicians")
    search_fields = ("technician__user__email",)
    readonly_fields = ("id",)


@admin.register(TechnicianShift)
class TechnicianShiftAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {"tenant": "Firma"}
    list_display = ("technician", "date", "start_time", "end_time", "tenant")
    list_filter = ("tenant", "date")
    search_fields = ("technician__email", "technician__first_name", "technician__last_name")
    date_hierarchy = "date"
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("technician",)


@admin.register(TechnicianAttendance)
class TechnicianAttendanceAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name_plural = "Teknisyen Devam Durumları"
    admin_field_labels = {
        "tenant": "Firma", "start_time": "Başlangıç Saati", "end_time": "Bitiş Saati",
        "created_at": "Oluşturulma Tarihi", "updated_at": "Güncellenme Tarihi",
    }
    list_display = ("technician", "date", "status", "source", "start_time", "end_time", "tenant")
    list_filter = ("tenant", "status", "source", "date")
    search_fields = ("technician__user__email", "technician__user__first_name", "technician__user__last_name", "note")
    date_hierarchy = "date"
    readonly_fields = ("id", "created_at", "updated_at")
    autocomplete_fields = ("technician",)


@admin.register(LocationLog)
class LocationLogAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name = "Konum Takip Kaydı"
    admin_verbose_name_plural = "Konum Takip Kayıtları"
    admin_field_labels = {
        "tenant": "Firma", "user": "Kullanıcı", "technician": "Teknisyen", "service": "Servis",
        "customer": "Müşteri", "latitude": "Enlem", "longitude": "Boylam",
        "customer_latitude": "Müşteri Enlemi", "customer_longitude": "Müşteri Boylamı",
        "last_distance_meters": "Son Mesafe (Metre)", "arrived_at": "Varış Tarihi",
        "last_seen_at": "Son Görülme", "left_at": "Ayrılış Tarihi",
        "created_at": "Oluşturulma Tarihi", "updated_at": "Güncellenme Tarihi",
    }
    list_display = ("user", "service", "customer", "arrived_at", "last_seen_at", "left_at", "last_distance_meters")
    list_filter = ("tenant",)
    search_fields = ("user__email", "user__first_name", "user__last_name",
                     "service__receipt_number", "customer__full_name")
    date_hierarchy = "arrived_at"
    readonly_fields = ("id", "created_at", "updated_at")
    raw_id_fields = ("user", "technician", "service", "customer")
