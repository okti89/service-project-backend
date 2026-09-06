from django.contrib import admin

from core.admin import TurkishAdminMixin

from .models import Feedback


@admin.register(Feedback)
class FeedbackAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {"user": "Kullanıcı", "feedback_type": "Tür", "created_at": "Oluşturulma Tarihi", "updated_at": "Güncellenme Tarihi", "tenant": "Firma"}
    list_display = ("subject", "feedback_type", "user", "tenant", "status", "created_at")
    list_filter = ("feedback_type", "status", "tenant", "created_at")
    search_fields = ("subject", "message", "user__email", "user__first_name", "user__last_name")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("user",)
    date_hierarchy = "created_at"
