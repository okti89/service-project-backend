from django.contrib import admin

from core.admin import TurkishAdminMixin

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name = "Müşteri"
    admin_verbose_name_plural = "Müşteriler"
    admin_field_labels = {
        "full_name": "Ad Soyad",
        "phone_number": "Telefon",
        "email": "E-posta",
        "address": "Adres",
        "note": "Not",
        "tenant": "Firma",
        "created_at": "Oluşturulma Tarihi",
        "updated_at": "Güncellenme Tarihi",
    }
    list_display = ("full_name", "phone_number", "email", "tenant", "is_deleted", "created_at")
    list_filter = ("tenant", "is_deleted")
    search_fields = ("full_name", "phone_number", "email", "address")
    readonly_fields = ("id", "created_at", "updated_at")
    date_hierarchy = "created_at"
