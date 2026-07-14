from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from import_export.admin import ImportExportModelAdmin

from .models import User,UserDevice
from technicians.services import ensure_technician_profile

@admin.register(User)
class CustomUserAdmin(ImportExportModelAdmin, BaseUserAdmin):
    list_display = ('email', 'phone_number', 'first_name', 'last_name', 'tenant', 'user_type','approval_status_badge','is_staff', 'is_active', 'avatar_thumb')
    list_display_links = ('email', 'first_name', 'last_name')
    list_filter = ('tenant', 'is_staff', 'approval_status','user_type','is_superuser', 'is_active')
    search_fields = ('email', 'first_name', 'last_name', 'phone_number')
    ordering = ('email',)
    readonly_fields = ('id', 'date_joined', 'avatar_thumb')
    actions = ['approve_users', 'reject_users', 'mark_as_pending']

    fieldsets = (
        (None, {'fields': ('email', 'password', 'id')}),
        (_('Kullanıcı Bilgileri'), {'fields': ('first_name', 'last_name', 'phone_number','approval_status','user_type')}),
        (_('Profil'), {'fields': ('avatar', 'avatar_thumb')}),
        (_('Parola Sıfırlama'), {'fields': ('password_reset_code', 'password_reset_code_sent_at')}),
        (_('Yetkiler'), {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        (_('Önemli Tarihler'), {'fields': ('last_login', 'date_joined')}),
        (_('Tenant'), {'fields': ('tenant',)}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'phone_number', 'password1', 'password2'),
        }),
    )

    def avatar_thumb(self, obj):
        if obj.avatar:
            try:
                return format_html(
                    '<img src="{}" style="height:40px;width:40px;object-fit:cover;border-radius:4px;" />',
                    obj.avatar.url
                )
            except:
                return '-'
        return '-'
    avatar_thumb.short_description = 'Avatar'

    def approval_status_badge(self, obj):
        color_map = {
            'pending': '#F59E0B',
            'approved': '#16A34A',
            'rejected': '#DC2626',
        }
        color = color_map.get(obj.approval_status, '#6B7280')
        label = obj.get_approval_status_display() or obj.approval_status
        return format_html(
            '<span style="background:{}15;color:{};padding:4px 10px;border-radius:6px;font-weight:700;font-size:11px;border:1px solid{}40;">{}</span>',
            color, color, color, label,
        )
    approval_status_badge.short_description = 'Onay Durumu'

    @admin.action(description='Seçili kullanıcıları onayla')
    def approve_users(self, request, queryset):
        updated = 0
        for user in queryset:
            if user.approval_status != 'approved':
                user.approval_status = 'approved'
                user.is_active = True
                user.save(update_fields=['approval_status', 'is_active'])
                ensure_technician_profile(user)
                updated += 1
        if updated:
            self.message_user(request, f'{updated} kullanıcı onaylandı.', level='success')
        else:
            self.message_user(request, 'Seçili kullanıcılar zaten onaylıydı.', level='info')

    @admin.action(description='Seçili kullanıcıları reddet')
    def reject_users(self, request, queryset):
        updated = 0
        for user in queryset:
            if user.approval_status != 'rejected':
                user.approval_status = 'rejected'
                user.is_active = False
                user.save(update_fields=['approval_status', 'is_active'])
                ensure_technician_profile(user)
                updated += 1
        if updated:
            self.message_user(request, f'{updated} kullanıcı reddedildi.', level='warning')
        else:
            self.message_user(request, 'Seçili kullanıcılar zaten reddedilmişti.', level='info')

    @admin.action(description='Seçili kullanıcıları onay bekliyor olarak işaretle')
    def mark_as_pending(self, request, queryset):
        updated = 0
        for user in queryset:
            if user.approval_status != 'pending':
                user.approval_status = 'pending'
                user.is_active = False
                user.save(update_fields=['approval_status', 'is_active'])
                ensure_technician_profile(user)
                updated += 1
        if updated:
            self.message_user(request, f'{updated} kullanıcı onay bekliyor olarak işaretlendi.', level='info')
        else:
            self.message_user(request, 'Seçili kullanıcılar zaten onay bekliyordu.', level='info')





admin.site.register(UserDevice,)
