from django.contrib import admin

from .models import Tenant, TenantMembership


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "app_name", "is_active", "created_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "code", "app_name")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("name",)


@admin.register(TenantMembership)
class TenantMembershipAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'period_number', 'premium_started_at', 'renewal_date', 'created_at')
    list_filter = ('tenant',)
    search_fields = ('tenant__name', 'tenant__code')
    readonly_fields = ('period_number', 'renewal_date', 'created_at')
    actions = ('renew_selected_memberships',)

    @admin.action(description='Seçili üyelikleri bir yıl yenile')
    def renew_selected_memberships(self, request, queryset):
        renewed = 0
        for membership in queryset:
            latest = membership.tenant.memberships.order_by('-period_number').first()
            if latest and latest.id == membership.id:
                membership.renew()
                renewed += 1
        self.message_user(request, f'{renewed} üyelik dönemi yenilendi.')