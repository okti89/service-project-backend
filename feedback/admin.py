from django.contrib import admin

from .models import Feedback


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("subject", "user", "tenant", "status", "created_at", "updated_at")
    list_filter = ("status", "tenant", "created_at")
    search_fields = ("subject", "message", "user__email", "user__first_name", "user__last_name")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("user",)
