from django.contrib import admin

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone_number", "email", "tenant", "is_deleted")
    list_filter = ("tenant", "is_deleted")
    search_fields = ("full_name", "phone_number", "email")
