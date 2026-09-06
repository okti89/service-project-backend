from django.contrib import admin

from core.admin import TurkishAdminMixin
from .models import Product, ProductCategory, StockMovement


@admin.register(ProductCategory)
class ProductCategoryAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name = "Ürün Kategorisi"
    admin_verbose_name_plural = "Ürün Kategorileri"
    admin_field_labels = {"name": "Kategori Adı", "tenant": "Firma"}
    list_display = ("name", "tenant")
    list_filter = ("tenant",)
    search_fields = ("name",)
    actions_on_top = True
    actions_on_bottom = True


@admin.register(Product)
class ProductAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name = "Ürün"
    admin_verbose_name_plural = "Ürünler"
    admin_field_labels = {
        "code": "Ürün Kodu", "name": "Ürün Adı", "tenant": "Firma", "category": "Kategori",
        "description": "Açıklama", "price": "Fiyat", "stock_quantity": "Stok Miktarı",
        "status": "Stok Durumu", "image": "Görsel", "is_active": "Aktif", "updated_at": "Güncellenme Tarihi",
    }
    list_display = ("code", "name", "tenant", "category", "price", "stock_quantity", "status", "is_active")
    list_filter = ("tenant", "status", "is_active", "category")
    search_fields = ("code", "name", "description")
    readonly_fields = ("updated_at",)
    autocomplete_fields = ("category",)
    actions_on_top = True
    actions_on_bottom = True


@admin.register(StockMovement)
class StockMovementAdmin(TurkishAdminMixin, admin.ModelAdmin):
    admin_verbose_name = "Stok Hareketi"
    admin_verbose_name_plural = "Stok Hareketleri"
    admin_field_labels = {
        "product": "Ürün", "technician": "Teknisyen", "movement_type": "Hareket Türü",
        "quantity": "Miktar", "tenant": "Firma", "description": "Açıklama", "created_at": "Oluşturulma Tarihi",
    }
    list_display = ("product", "technician", "movement_type", "quantity", "tenant", "created_at")
    list_filter = ("tenant", "movement_type", "created_at")
    search_fields = ("product__name", "product__code", "technician__email", "description")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("product", "technician")
    date_hierarchy = "created_at"
    actions_on_top = True
    actions_on_bottom = True
