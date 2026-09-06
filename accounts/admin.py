from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from import_export.admin import ImportExportModelAdmin
from rest_framework.authtoken.models import TokenProxy

from core.admin import TurkishAdminMixin
from .models import AccountDeletionRequest, User, UserDevice
from technicians.services import ensure_technician_profile


if admin.site.is_registered(TokenProxy):
    admin.site.unregister(TokenProxy)


@admin.register(TokenProxy)
class TokenAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name = 'API Anahtarı'
    admin_verbose_name_plural = 'API Anahtarları'
    admin_field_labels = {'key': 'Anahtar', 'user': 'Kullanıcı', 'created': 'Oluşturulma Tarihi'}
    list_display = ('key', 'user', 'created')
    search_fields = ('user__email', 'user__first_name', 'user__last_name')
    autocomplete_fields = ('user',)
    readonly_fields = ('key', 'created')

@admin.register(User)
class CustomUserAdmin(TurkishAdminMixin, ImportExportModelAdmin, BaseUserAdmin):
    admin_verbose_name = 'Kullanıcı'
    admin_verbose_name_plural = 'Kullanıcılar'
    admin_field_labels = {
        'email': 'E-posta', 'phone_number': 'Telefon', 'first_name': 'Ad', 'last_name': 'Soyad',
        'tenant': 'Firma', 'user_type': 'Kullanıcı Türü', 'approval_status': 'Onay Durumu',
        'is_platform_admin': 'Platform Yöneticisi', 'is_staff': 'Yönetim Paneline Erişebilir',
        'is_active': 'Aktif', 'date_joined': 'Kayıt Tarihi', 'last_login': 'Son Giriş',
        'pending_reminder_sent_at': 'Son Onay Hatırlatma Tarihi', 'pending_reminder_count': 'Onay Hatırlatma Sayısı',
    }
    list_display = ('email', 'phone_number', 'first_name', 'last_name', 'tenant', 'user_type', 'approval_status_badge', 'is_platform_admin', 'is_staff', 'is_active', 'avatar_thumb')
    list_display_links = ('email', 'first_name', 'last_name')
    list_filter = ('tenant', 'is_platform_admin', 'is_staff', 'approval_status','user_type','is_superuser', 'is_active')
    search_fields = ('email', 'first_name', 'last_name', 'phone_number')
    ordering = ('email',)
    readonly_fields = ('id', 'date_joined', 'avatar_thumb', 'pending_reminder_sent_at', 'pending_reminder_count')
    actions = ['approve_users', 'reject_users', 'mark_as_pending']

    fieldsets = (
        (None, {'fields': ('email', 'password', 'id')}),
        (_('Kullanıcı Bilgileri'), {'fields': ('first_name', 'last_name', 'phone_number','approval_status','user_type')}),
        (_('Profil'), {'fields': ('avatar', 'avatar_thumb')}),
        (_('Parola ve Hatırlatmalar'), {'fields': ('password_reset_code', 'password_reset_code_sent_at', 'pending_reminder_sent_at', 'pending_reminder_count')}),
        (_('Yetkiler'), {
            'fields': ('is_active', 'is_platform_admin', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        (_('Önemli Tarihler'), {'fields': ('last_login', 'date_joined')}),
        (_('Firma'), {'fields': ('tenant',)}),
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
            except (OSError, ValueError):
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
                updated += 1
        if updated:
            self.message_user(request, f'{updated} kullanıcı onay bekliyor olarak işaretlendi.', level='info')
        else:
            self.message_user(request, 'Seçili kullanıcılar zaten onay bekliyordu.', level='info')
@admin.register(UserDevice)
class UserDeviceAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name = 'Kullanıcı Cihazı'
    admin_verbose_name_plural = 'Kullanıcı Cihazları'
    admin_field_labels = {
        'tenant': 'Firma', 'user': 'Kullanıcı', 'device_id': 'Cihaz Kimliği', 'device_name': 'Cihaz Adı',
        'platform': 'Platform', 'expo_token': 'Expo Bildirim Anahtarı', 'location_permission': 'Konum İzni',
        'notification_permission': 'Bildirim İzni', 'is_active': 'Aktif', 'created_at': 'Oluşturulma Tarihi',
        'updated_at': 'Güncellenme Tarihi', 'last_used_at': 'Son Kullanım Tarihi',
    }
    list_display = ('user', 'device_name', 'platform', 'tenant', 'notification_permission', 'location_permission', 'is_active', 'last_used_at')
    list_filter = ('tenant', 'platform', 'notification_permission', 'location_permission', 'is_active')
    search_fields = ('user__email', 'user__first_name', 'user__last_name', 'device_id', 'device_name', 'expo_token')
    autocomplete_fields = ('user',)
    readonly_fields = ('created_at', 'updated_at', 'last_used_at')


@admin.register(AccountDeletionRequest)
class AccountDeletionRequestAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {
        'email': 'E-posta', 'note': 'Not', 'status': 'Durum',
        'created_at': 'Oluşturulma Tarihi', 'processed_at': 'İşlenme Tarihi',
    }
    list_display = ("email", "status", "created_at", "processed_at")
    list_filter = ("status",)
    search_fields = ("email",)
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
