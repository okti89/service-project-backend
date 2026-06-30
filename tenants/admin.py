from django.contrib import admin

from .models import Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "app_name", "is_active", "created_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "code", "app_name")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("name",)
