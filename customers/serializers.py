from rest_framework import serializers
from django.db import transaction
from .models import Customer


class CustomerSerializer(serializers.ModelSerializer):
    tenant = serializers.UUIDField(source="tenant_id", read_only=True)

    class Meta:
        model = Customer
        fields = "__all__"
        read_only_fields = ("id", "tenant", "created_at", "updated_at")

    @staticmethod
    def normalize_phone(value):
        digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
        if not digits:
            return ''

        if digits.startswith('90') and len(digits) > 10:
            digits = digits[2:]
        elif digits.startswith('090') and len(digits) > 11:
            digits = digits[3:]

        if not digits.startswith('0') and len(digits) == 10:
            digits = '0' + digits

        return digits

    def validate(self, attrs):
        request = self.context.get("request")
        tenant = getattr(getattr(request, "user", None), "tenant", None)

        phone = attrs.get("phone_number")

        if phone:
            normalized_phone = self.normalize_phone(phone)
            attrs["phone_number"] = normalized_phone

            if tenant:
                qs = Customer.objects.filter(
                    tenant=tenant,
                    phone_number=normalized_phone
                )

                if self.instance:
                    qs = qs.exclude(pk=self.instance.pk)

                if qs.exists():
                    raise serializers.ValidationError({
                        "phone_number": "Bu telefon numarası bu firma için zaten kayıtlı."
                    })

        return attrs
