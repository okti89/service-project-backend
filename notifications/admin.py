from django.contrib import admin
from .models import Notification
from import_export.admin import ImportExportModelAdmin

class NotificationAdmin(ImportExportModelAdmin):
    list_display = ('user', 'tenant', 'title', 'is_read', 'created_at')
    list_filter = ('tenant', 'is_read',)
    search_fields = ('user__email', 'title', 'message')
    readonly_fields = ('created_at',)
    actions = ['mark_as_read', 'mark_as_unread']


admin.site.register(Notification, NotificationAdmin)
