from rest_framework import serializers
from .models import CompanyConfig, WorkingHour, HolidayException


# =========================
# BASE VALIDATION MIXIN
# =========================
class TenantValidationMixin:

    def validate_company_tenant(self, company, request):
        tenant = getattr(getattr(request, "user", None), "tenant", None)
        if company and tenant and company.tenant_id != tenant.id:
            raise serializers.ValidationError("Bu kayıt bu tenant'a ait değil.")


# =========================
# WORKING HOUR
# =========================
class WorkingHourSerializer(TenantValidationMixin, serializers.ModelSerializer):

    day_label = serializers.CharField(source='get_day_of_week_display', read_only=True)

    class Meta:
        model = WorkingHour
        fields = [
            "id",
            "company",
            "day_of_week",
            "day_label",
            "start_time",
            "end_time",
            "is_holiday",
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        company = attrs.get("company") or getattr(self.instance, "company", None)
        self.validate_company_tenant(company, request)
        return attrs


# =========================
# HOLIDAY EXCEPTION
# =========================
class HolidayExceptionSerializer(TenantValidationMixin, serializers.ModelSerializer):

    class Meta:
        model = HolidayException
        fields = [
            "id",
            "company",
            "title",
            "start_date",
            "end_date",
            "is_half_day",
            "note",
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        company = attrs.get("company") or getattr(self.instance, "company", None)
        self.validate_company_tenant(company, request)
        return attrs


# =========================
# COMPANY CONFIG
# =========================
class CompanyConfigSerializer(serializers.ModelSerializer):

    working_hours = WorkingHourSerializer(many=True, read_only=True)
    holiday_exceptions = HolidayExceptionSerializer(many=True, read_only=True)

    active_users_count = serializers.SerializerMethodField()
    remaining_users = serializers.SerializerMethodField()
    tenant_code = serializers.CharField(source='tenant.code', read_only=True)

    class Meta:
        model = CompanyConfig
        fields = [
            "id",
            "tenant",
            "tenant_code",
            "name",
            "panel_url",
            "logo",
            "phone_number",
            "email",
            "address",
            "max_users",
            "force_update",
            "store_update_url_android",
            "store_update_url_ios",
            "store_android_version",
            "store_ios_version",
            "working_hours",
            "holiday_exceptions",
            "active_users_count",
            "remaining_users",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("tenant",)

    def get_active_users_count(self, obj):
        tenant = obj.tenant
        return tenant.users.filter(is_active=True).count() if tenant else 0

    def get_remaining_users(self, obj):
        active = self.get_active_users_count(obj)
        return max((obj.max_users or 0) - active, 0)