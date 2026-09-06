from django.contrib import admin

from core.admin import TurkishAdminMixin
from .models import Account, Transaction, TransactionCategory


@admin.register(Account)
class AccountAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {"name": "Hesap Adı", "tenant": "Firma", "company": "Şirket", "account_type": "Hesap Türü", "balance": "Bakiye"}
    list_display = ("name", "tenant", "company", "account_type", "balance", "updated_at")
    list_filter = ("tenant", "company", "account_type")
    search_fields = ("name", "company__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(TransactionCategory)
class TransactionCategoryAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {"type": "Tür", "tenant": "Firma", "company": "Şirket"}
    list_display = ("name", "type", "tenant", "company")
    list_filter = ("type", "tenant", "company")
    search_fields = ("name", "company__name")


@admin.register(Transaction)
class TransactionAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_field_labels = {
        "transaction_type": "İşlem Türü", "account": "Hesap", "category": "Kategori", "amount": "Tutar",
        "date": "İşlem Tarihi", "tenant": "Firma", "company": "Şirket", "description": "Açıklama",
        "receipt_number": "Belge Numarası", "service": "Servis", "created_at": "Oluşturulma Tarihi",
        "is_retrieved": "Geri Alındı",
    }
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
    date_hierarchy = "date"
