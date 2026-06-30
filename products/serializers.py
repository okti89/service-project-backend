from rest_framework import serializers

from .models import Product, ProductCategory, StockMovement


class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ["id", "name"]
        read_only_fields = ["id"]


class ProductSerializer(serializers.ModelSerializer):
    category_detail = ProductCategorySerializer(source="category", read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=ProductCategory.objects.all(),
        source="category",
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Product
        fields = [
            "id",
            "category_detail",
            "category_id",
            "name",
            "code",
            "description",
            "price",
            "stock_quantity",
            "status",
            "image",
            "is_active",
            "updated_at",
        ]
        read_only_fields = ["id", "code", "status", "updated_at"]

    def validate(self, attrs):
        request = self.context.get("request")
        tenant = getattr(getattr(request, "user", None), "tenant", None)
        category = attrs.get("category")

        if category and tenant and category.tenant_id != tenant.id:
            raise serializers.ValidationError(
                {"category_id": "Bu kategori bu tenant'a ait degil."}
            )

        return attrs


class StockMovementSerializer(serializers.ModelSerializer):
    product_detail = ProductSerializer(source="product", read_only=True)
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(),
        source="product",
        write_only=True,
    )
    movement_type_display = serializers.CharField(
        source="get_movement_type_display",
        read_only=True,
    )
    technician_id = serializers.IntegerField(
        source="technician.id",
        read_only=True,
    )
    technician_name = serializers.SerializerMethodField()

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "product_detail",
            "product_id",
            "movement_type",
            "movement_type_display",
            "technician",
            "technician_id",
            "technician_name",
            "quantity",
            "description",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        request = self.context.get("request")
        tenant = getattr(getattr(request, "user", None), "tenant", None)
        product = attrs.get("product")
        technician = attrs.get("technician")

        if product and tenant and product.tenant_id != tenant.id:
            raise serializers.ValidationError(
                {"product_id": "Bu urun bu tenant'a ait degil."}
            )

        if technician and tenant and getattr(technician, "tenant_id", None) != tenant.id:
            raise serializers.ValidationError(
                {"technician": "Bu kullanici bu tenant'a ait degil."}
            )

        return attrs

    def get_technician_name(self, obj):
        if not obj.technician:
            return None

        user = obj.technician
        return getattr(user, "get_full_name", lambda: None)() or user.email
