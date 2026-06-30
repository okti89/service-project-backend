from .models import TechnicianCompensation, Payroll, PayrollComponent, PayrollTemplate
from rest_framework import serializers


class PayrollTemplateSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        request = self.context.get("request")
        tenant = getattr(getattr(request, "user", None), "tenant", None)

        template_tenant = attrs.get("tenant") or getattr(self.instance, "tenant", None)

        if tenant and template_tenant and template_tenant != tenant:
            raise serializers.ValidationError({"detail": "Sablon tenant bilgisi gecersiz."})

        return attrs

    class Meta:
        model = PayrollTemplate
        fields = '__all__'
        read_only_fields = ('tenant',)


class PayrollComponentSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        request = self.context.get("request")
        tenant = getattr(getattr(request, "user", None), "tenant", None)

        payroll = attrs.get("payroll") or getattr(self.instance, "payroll", None)

        if payroll and tenant:
            payroll_tenant = getattr(payroll, "tenant", None)
            if payroll_tenant != tenant:
                raise serializers.ValidationError({"payroll": "Bu bordro bu tenant'a ait degil."})

        return attrs

    class Meta:
        model = PayrollComponent
        fields = '__all__'

class PayrollSerializer(serializers.ModelSerializer):
    components = PayrollComponentSerializer(many=True, read_only=True)
    base_salary = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    technician_name = serializers.SerializerMethodField()
    technician_email = serializers.SerializerMethodField()

    class Meta:
        model = Payroll
        fields = '__all__'
        read_only_fields = (
            'total_premiums',
            'total_deductions',
            'net_salary',
            'created_at',
            'updated_at'
        )

    def get_technician_name(self, obj):
        user = getattr(getattr(obj, "technician", None), "user", None)
        if not user:
            return None
        return user.get_full_name() or user.email

    def get_technician_email(self, obj):
        user = getattr(getattr(obj, "technician", None), "user", None)
        return getattr(user, "email", None)

    def create(self, validated_data):
        technician = validated_data.get('technician')
        request = self.context.get("request")
        tenant = getattr(getattr(request, "user", None), "tenant", None)

        if tenant:
            validated_data["tenant"] = tenant

        if tenant and technician:
            tech_tenant = getattr(getattr(technician, "user", None), "tenant", None)
            if tech_tenant != tenant:
                raise serializers.ValidationError({'technician': "Bu teknisyen bu tenant'a ait degil."})

        base_salary = validated_data.get('base_salary')

        if base_salary is None and technician:
            compensation = TechnicianCompensation.objects.filter(technician=technician).first()
            base_salary = compensation.base_salary if compensation else None

        if base_salary is None:
            raise serializers.ValidationError({
                'base_salary': 'Taban maas zorunludur.'
            })

        validated_data['base_salary'] = base_salary

        payroll = super().create(validated_data)

        # sadece hesaplama
        payroll.calculate_totals()
        payroll.save(update_fields=[
            'total_premiums',
            'total_deductions',
            'net_salary',
            'updated_at'
        ])

        # accounting sync tek noktaya indirildi (çift çağrı riskini azaltır)
        payroll.sync_accounting_transaction()

        return payroll

    def update(self, instance, validated_data):
        validated_data.pop('base_salary', None)
        validated_data.pop('tenant', None)

        payroll = super().update(instance, validated_data)

        payroll.calculate_totals()

        update_fields = [
            'total_premiums',
            'total_deductions',
            'net_salary',
            'updated_at'
        ]

        if payroll.status == "paid" and not payroll.paid_date:
            from django.utils import timezone
            payroll.paid_date = timezone.now()
            update_fields.append('paid_date')

        if payroll.status != "paid" and payroll.paid_date:
            payroll.paid_date = None
            update_fields.append('paid_date')

        payroll.save(update_fields=update_fields)

        payroll.sync_accounting_transaction()

        return payroll

class TechnicianCompensationSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        request = self.context.get("request")
        tenant = getattr(getattr(request, "user", None), "tenant", None)

        technician = attrs.get("technician") or getattr(self.instance, "technician", None)

        if tenant and technician:
            tech_tenant = getattr(getattr(technician, "user", None), "tenant", None)
            if tech_tenant != tenant:
                raise serializers.ValidationError({"technician": "Bu teknisyen bu tenant'a ait degil."})

        return attrs

    class Meta:
        model = TechnicianCompensation
        fields = '__all__'
        read_only_fields = ('tenant',)
