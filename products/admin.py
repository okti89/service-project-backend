from django.contrib import admin

from .models import Product, ProductCategory, StockMovement


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant")
    list_filter = ("tenant",)
    search_fields = ("name",)
    actions_on_top = True
    actions_on_bottom = True


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "tenant", "category", "price", "stock_quantity", "status", "is_active")
    list_filter = ("tenant", "status", "is_active", "category")
    search_fields = ("code", "name", "description")
    readonly_fields = ("updated_at",)
    autocomplete_fields = ("category",)
    actions_on_top = True
    actions_on_bottom = True


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("product", "technician", "movement_type", "quantity", "tenant", "created_at")
    list_filter = ("tenant", "movement_type", "created_at")
    search_fields = ("product__name", "product__code", "technician__email", "description")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("product", "technician")
    actions_on_top = True
    actions_on_bottom = True
