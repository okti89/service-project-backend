from django.contrib import admin

from core.admin import TurkishAdminMixin
from .models import Quote, QuoteItem


class QuoteItemInline(admin.TabularInline):
    model = QuoteItem
    extra = 0
    autocomplete_fields = ("product",)
    fields = ("product", "name", "description", "quantity", "unit_price", "line_total")
    readonly_fields = ("line_total",)

    @admin.display(description="Toplam Tutar")
    def line_total(self, obj):
        return obj.total_price if obj else 0


@admin.register(Quote)
class QuoteAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name = "Teklif"
    admin_verbose_name_plural = "Teklifler"
    admin_field_labels = {
        "quote_number": "Teklif Numarası",
        "customer": "Müşteri",
        "tenant": "Firma",
        "note": "Not",
        "valid_until": "Geçerlilik Tarihi",
        "created_by": "Oluşturan",
        "converted_service": "Dönüştürülen Servis",
        "sent_at": "Gönderilme Tarihi",
        "created_at": "Oluşturulma Tarihi",
        "updated_at": "Güncellenme Tarihi",
    }
    list_display = ("quote_number", "customer", "tenant", "quote_total", "valid_until", "sent_at", "converted_service")
    search_fields = ("quote_number", "customer__full_name", "customer__phone_number")
    list_filter = ("tenant", "valid_until", "sent_at", "created_at")
    autocomplete_fields = ("customer", "created_by", "converted_service")
    readonly_fields = ("quote_number", "quote_total", "created_at", "updated_at")
    date_hierarchy = "created_at"
    inlines = [QuoteItemInline]

    @admin.display(description="Toplam Tutar")
    def quote_total(self, obj):
        return obj.total_price if obj else 0


@admin.register(QuoteItem)
class QuoteItemAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name = "Teklif İşlemi"
    admin_verbose_name_plural = "Teklif İşlemleri"
    admin_field_labels = {"quote": "Teklif", "product": "Ürün", "name": "İşlem Adı", "description": "Açıklama", "quantity": "Adet", "unit_price": "Birim Fiyat"}
    list_display = ("quote", "name", "quantity", "unit_price", "line_total")
    search_fields = ("quote__quote_number", "name", "description", "product__name")
    list_filter = ("quote__tenant",)
    autocomplete_fields = ("quote", "product")
    readonly_fields = ("line_total",)

    @admin.display(description="Toplam Tutar")
    def line_total(self, obj):
        return obj.total_price if obj else 0
