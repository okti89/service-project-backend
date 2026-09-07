from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from customers.models import Customer
from products.models import Product
from technicians.models import Technician

from .models import Quote, QuoteItem


class QuoteCustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["id", "full_name", "phone_number", "email", "address"]


class QuoteItemSerializer(serializers.ModelSerializer):
    total_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    product = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(),
        required=False,
        allow_null=True,
    )
    unit_price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=Decimal("0.00"),
    )

    class Meta:
        model = QuoteItem
        fields = [
            "id",
            "product",
            "name",
            "description",
            "quantity",
            "unit_price",
            "total_price",
        ]
        read_only_fields = ["id", "total_price"]

    def validate(self, attrs):
        request = self.context.get("request")
        tenant = getattr(getattr(request, "user", None), "tenant", None)
        product = attrs.get("product")
        name = str(attrs.get("name") or "").strip()
        unit_price = attrs.get("unit_price")

        if product and product.tenant_id != getattr(tenant, "id", None):
            raise serializers.ValidationError(
                {"product": "Secilen urun baska bir firmaya ait."}
            )
        if not product and not name:
            raise serializers.ValidationError({"name": "İşlem adı zorunludur."})
        if not product and unit_price is None:
            raise serializers.ValidationError({"unit_price": "Birim fiyat zorunludur."})
        return attrs


class QuoteSerializer(serializers.ModelSerializer):
    customer_detail = QuoteCustomerSerializer(source="customer", read_only=True)
    items = QuoteItemSerializer(many=True)
    total_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Quote
        fields = [
            "id",
            "quote_number",
            "customer",
            "customer_detail",
            "note",
            "valid_until",
            "status",
            "items",
            "total_price",
            "created_by",
            "created_by_name",
            "converted_service",
            "sent_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "quote_number",
            "status",
            "created_by",
            "converted_service",
            "sent_at",
            "created_at",
            "updated_at",
        ]

    def get_created_by_name(self, obj):
        if not obj.created_by:
            return None
        return obj.created_by.get_full_name() or obj.created_by.email

    def validate_customer(self, customer):
        request = self.context.get("request")
        tenant = getattr(getattr(request, "user", None), "tenant", None)
        if customer.tenant_id != getattr(tenant, "id", None):
            raise serializers.ValidationError("Secilen musteri baska bir firmaya ait.")
        if customer.is_deleted:
            raise serializers.ValidationError("Silinmis musteri icin teklif olusturulamaz.")
        return customer

    def validate_valid_until(self, value):
        if value and value < timezone.localdate():
            raise serializers.ValidationError("Gecerlilik tarihi gecmiste olamaz.")
        return value

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError("En az bir teklif işlemi eklenmelidir.")
        return items

    def validate(self, attrs):
        if self.instance and self.instance.converted_service_id:
            raise serializers.ValidationError(
                "Servise donusturulmus teklif degistirilemez."
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items")
        quote = Quote.objects.create(**validated_data)
        QuoteItem.objects.bulk_create(
            [self._build_item(quote, item) for item in items]
        )
        return quote

    @transaction.atomic
    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()

        if items is not None:
            instance.items.all().delete()
            QuoteItem.objects.bulk_create(
                [self._build_item(instance, item) for item in items]
            )
        return instance

    @staticmethod
    def _build_item(quote, item):
        product = item.get("product")
        return QuoteItem(
            quote=quote,
            product=product,
            name=item.get("name") or getattr(product, "name", ""),
            description=item.get("description") or "",
            quantity=item.get("quantity", 1),
            unit_price=(
                item.get("unit_price")
                if item.get("unit_price") is not None
                else getattr(product, "price", 0)
            ),
        )


class QuoteConvertSerializer(serializers.Serializer):
    scheduled_date = serializers.DateTimeField()
    technician = serializers.PrimaryKeyRelatedField(
        queryset=Technician.objects.all(),
        required=False,
        allow_null=True,
    )

    def validate_technician(self, technician):
        request = self.context.get("request")
        tenant = getattr(getattr(request, "user", None), "tenant", None)
        if technician and technician.tenant_id != getattr(tenant, "id", None):
            raise serializers.ValidationError("Secilen teknisyen baska bir firmaya ait.")
        return technician


class QuoteEmailSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    subject = serializers.CharField(required=False, allow_blank=True, max_length=255)
    message = serializers.CharField(required=False, allow_blank=True)


class QuoteStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[
            Quote.STATUS_DRAFT,
            Quote.STATUS_SENT,
            Quote.STATUS_CANCELLED,
        ]
    )
