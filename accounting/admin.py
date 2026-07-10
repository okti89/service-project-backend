from django.contrib import admin

from .models import Account, Transaction, TransactionCategory


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "company", "account_type", "balance", "updated_at")
    list_filter = ("tenant", "company", "account_type")
    search_fields = ("name", "company__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(TransactionCategory)
class TransactionCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "tenant", "company")
    list_filter = ("type", "tenant", "company")
    search_fields = ("name", "company__name")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_type",
        "account",
        "category",
        "amount",
        "date",
        "tenant",
        "is_retrieved",
    )
    list_filter = ("transaction_type", "tenant", "company", "is_retrieved", "date")
    search_fields = ("receipt_number", "description", "account__name", "category__name")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("account", "category", "service")
