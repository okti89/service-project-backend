from django.contrib import admin
from django.utils import timezone

from core.admin import TurkishAdminMixin
from .models import Notification
from import_export.admin import ImportExportModelAdmin


@admin.register(Notification)
class NotificationAdmin(TurkishAdminMixin, ImportExportModelAdmin):
    admin_verbose_name = "Bildirim"
    admin_verbose_name_plural = "Bildirimler"
    admin_field_labels = {
        "tenant": "Firma",
        "user": "Kullanıcı",
        "title": "Başlık",
        "message": "Mesaj",
        "is_read": "Okundu",
        "read_at": "Okunma Tarihi",
        "created_at": "Oluşturulma Tarihi",
    }
    list_display = ('user', 'tenant', 'title', 'is_read', 'created_at')
    list_filter = ('tenant', 'is_read', 'created_at')
    search_fields = ('user__email', 'title', 'message')
    readonly_fields = ('created_at',)
    actions = ['mark_as_read', 'mark_as_unread']
    autocomplete_fields = ('user',)
    date_hierarchy = 'created_at'

    @admin.action(description="Seçili bildirimleri okundu olarak işaretle")
    def mark_as_read(self, request, queryset):
        updated = queryset.update(is_read=True, read_at=timezone.now())
        self.message_user(request, f"{updated} bildirim okundu olarak işaretlendi.")

    @admin.action(description="Seçili bildirimleri okunmadı olarak işaretle")
    def mark_as_unread(self, request, queryset):
        updated = queryset.update(is_read=False, read_at=None)
        self.message_user(request, f"{updated} bildirim okunmadı olarak işaretlendi.")
