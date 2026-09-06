from django.contrib import admin

from core.admin import TurkishAdminMixin
from maps.models import MapCache, MapQuotaPolicy, TenantMapQuota


@admin.register(TenantMapQuota)
class TenantMapQuotaAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name = "Firma Harita Kotası"
    admin_verbose_name_plural = "Firma Harita Kotaları"
    admin_field_labels = {
        "tenant": "Firma", "api_type": "API Türü", "year": "Yıl", "month": "Ay",
        "request_count": "İstek Sayısı", "last_request_at": "Son İstek Tarihi", "created_at": "Oluşturulma Tarihi",
    }
    list_display = ("tenant", "api_type", "year", "month", "request_count", "last_request_at")
    list_filter = ("api_type", "year", "month")
    search_fields = ("tenant__name",)
    readonly_fields = ("last_request_at", "created_at")


@admin.register(MapQuotaPolicy)
class MapQuotaPolicyAdmin(TurkishAdminMixin, admin.ModelAdmin):
    """Firma bazlı veya genel harita kota limitlerini yönetir.

    Firma seçiliyse politika yalnızca o firma için geçerlidir.
    Firma boşsa ve kapsam genelse tüm firmalar için varsayılan olur.
    """
    admin_field_labels = {
        "scope": "Kapsam", "tenant": "Firma", "api_type": "API Türü", "monthly_limit": "Aylık Sınır",
        "is_active": "Aktif", "notes": "Notlar", "created_at": "Oluşturulma Tarihi",
        "updated_at": "Güncellenme Tarihi", "updated_by": "Güncelleyen",
    }
    list_display = (
        "scope",
        "tenant",
        "api_type",
        "monthly_limit",
        "is_active",
        "updated_at",
        "updated_by",
    )
    list_filter = ("scope", "api_type", "is_active")
    search_fields = ("tenant__name", "notes")
    autocomplete_fields = ("tenant",)
    readonly_fields = ("created_at", "updated_at")
    list_editable = ("monthly_limit", "is_active")
    actions = ["activate_policies", "deactivate_policies"]

    @admin.action(description="Seçili politikaları aktifleştir")
    def activate_policies(self, request, queryset):
        n = queryset.update(is_active=True)
        self.message_user(request, f"{n} politika aktifleştirildi.")

    @admin.action(description="Seçili politikaları pasifleştir")
    def deactivate_policies(self, request, queryset):
        n = queryset.update(is_active=False)
        self.message_user(request, f"{n} politika pasifleştirildi.")

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(MapCache)
class MapCacheAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name = "Harita Önbelleği"
    admin_verbose_name_plural = "Harita Önbellekleri"
    admin_field_labels = {
        "tenant": "Firma", "cache_key": "Önbellek Anahtarı", "result": "Sonuç",
        "ttl_days": "Saklama Süresi (Gün)", "created_at": "Oluşturulma Tarihi",
    }
    list_display = ("tenant", "cache_key", "ttl_days", "created_at")
    search_fields = ("tenant__name", "cache_key")
    readonly_fields = ("created_at",)
