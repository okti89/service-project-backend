from rest_framework import serializers

from .models import (
    Account,
    TransactionCategory,
    Transaction
)
class AccountSerializer(serializers.ModelSerializer):

    class Meta:
        model = Account
        fields = '__all__'
        read_only_fields = (
            'tenant',
            'company',
        )

class TransactionCategorySerializer(serializers.ModelSerializer):

    class Meta:
        model = TransactionCategory
        fields = '__all__'
        read_only_fields = ('tenant', 'company')

class TransactionSerializer(serializers.ModelSerializer):

    class Meta:
        model = Transaction
        fields = '__all__'
        read_only_fields = ('tenant', 'company', 'is_retrieved')

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        tenant = getattr(user, "tenant", None)

        account = attrs.get(
            "account",
            getattr(self.instance, "account", None)
        )

        category = attrs.get(
            "category",
            getattr(self.instance, "category", None)
        )

        service = attrs.get(
            "service",
            getattr(self.instance, "service", None)
        )

        transaction_type = attrs.get(
            "transaction_type",
            getattr(self.instance, "transaction_type", None)
        )

        # Account tenant kontrolü
        if account and tenant:
            if account.tenant_id != tenant.id:
                raise serializers.ValidationError({
                    "account": "Bu hesap bu tenant'a ait değil."
                })

        # Category tenant kontrolü
        if category and tenant:
            if category.tenant_id != tenant.id:
                raise serializers.ValidationError({
                    "category": "Bu kategori bu tenant'a ait değil."
                })

        # Category type kontrolü
        if category and transaction_type:
            if category.type != transaction_type:
                raise serializers.ValidationError({
                    "category": "Kategori işlem türüyle uyuşmuyor."
                })

        # Service tenant kontrolü
        if service and tenant:
            if service.tenant_id != tenant.id:
                raise serializers.ValidationError({
                    "service": "Bu servis bu tenant'a ait değil."
                })

        return attrs
