from django.contrib import admin

from maps.models import MapCache, MapQuotaPolicy, TenantMapQuota


@admin.register(TenantMapQuota)
class TenantMapQuotaAdmin(admin.ModelAdmin):
    list_display = ("tenant", "api_type", "year", "month", "request_count", "last_request_at")
    list_filter = ("api_type", "year", "month")
    search_fields = ("tenant__name",)
    readonly_fields = ("last_request_at", "created_at")


@admin.register(MapQuotaPolicy)
class MapQuotaPolicyAdmin(admin.ModelAdmin):
    """Tenant bazli veya global harita kota limitlerini yonetir.

    Tenant secili ise sadece o tenant icin gecerli (override).
    Tenant bossa ve scope='global' ise tum tenant'lar icin default olur.
    """
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
        if not change:  # yeni olusturuluyorsa
            obj.updated_by = request.user
        else:
            obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(MapCache)
class MapCacheAdmin(admin.ModelAdmin):
    list_display = ("tenant", "cache_key", "ttl_days", "created_at")
    search_fields = ("tenant__name", "cache_key")
    readonly_fields = ("created_at",)
