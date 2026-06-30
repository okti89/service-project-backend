from rest_framework import serializers
from accounts.serializers import UserSerializer
from .models import (TechnicianStatus, TechnicianPermissions, TechnicianShift, 
TechnicianLocation, TechnicianAttendance, Technician,LocationLog)



STATUS_COLOR_FALLBACKS = {
    "available": "#28a745",
    "offduty": "#ffc107",
}



class TechnicianStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = TechnicianStatus
        fields = ["id", "name", "color"]

class TechnicianPermissionsSerializer(serializers.ModelSerializer):
    class Meta:
        model = TechnicianPermissions
        fields = [
            "id",
            "technician",
            "can_manage_customers",
            "can_manage_inventory",
            "can_manage_users",
            "can_manage_accounting",
            "can_manage_notifications",
            "can_manage_hr",
            "can_manage_reports",
            "can_manage_settings",
            "can_manage_services",            
            "can_manage_technicians"
        ]
        read_only_fields = ["id", "technician"]


class TechnicianShiftSerializer(serializers.ModelSerializer):
    class Meta:
        model = TechnicianShift
        fields = [
            "id",
            "technician",
            "date",
            "start_time",
            "end_time",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

class TechnicianLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TechnicianLocation
        fields = ["id", "technician", "location", "latitude", "longitude", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

class TechnicianAttendanceSerializer(serializers.ModelSerializer):
    technician_name = serializers.SerializerMethodField()

    class Meta:
        model = TechnicianAttendance
        fields = [
            "id",
            "technician",
            "technician_name",
            "date",
            "status",
            "start_time",
            "end_time",
            "note",
            "source",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "source", "created_at", "updated_at", "technician_name"]

    def get_technician_name(self, obj):
        if obj.technician and obj.technician.user:
            return obj.technician.user.get_full_name()
        return ""

class LocationLogSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    service_receipt_number = serializers.CharField(source="service.receipt_number", read_only=True)
    customer_name = serializers.CharField(source="customer.full_name", read_only=True)

    class Meta:
        model = LocationLog
        fields = [
            "id",
            "user",
            "user_name",
            "technician",
            "service",
            "service_receipt_number",
            "customer",
            "customer_name",
            "latitude",
            "longitude",
            "customer_latitude",
            "customer_longitude",
            "last_distance_meters",
            "arrived_at",
            "last_seen_at",
            "left_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_user_name(self, obj):
        return obj.user.get_full_name()


class TechnicianListSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    full_name = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    status_info = serializers.SerializerMethodField()
    is_self = serializers.SerializerMethodField()

    class Meta:
        model = Technician
        fields = [
            "id",
            "user",
            "full_name",
            "status",
            "status_display",
            "is_self",
            "hire_date",
            "is_online",
            "last_online",
            "created_at",
            "updated_at",
            "permissions",
            "status_info",
        ]

    def get_full_name(self, obj):
        if obj.user:
            return obj.user.get_full_name()
        return ""

    def get_permissions(self, obj):
        permission_obj = getattr(obj, "permissions", None)
        if not permission_obj:
            return {
                "can_manage_customers": False,
                "can_manage_inventory": False,
                "can_manage_users": False,
                "can_manage_accounting": False,
                "can_manage_notifications": False,
                "can_manage_hr": False,
                "can_manage_reports": False,
                "can_manage_settings": False,
                "can_manage_services": False,
                "can_use_global_search": False,
                "can_manage_technicians":False
            }

        return TechnicianPermissionsSerializer(permission_obj).data

    def get_status(self, obj):
        if not obj.status:
            return "available"
        return (obj.status.name or "available").strip().lower()

    def get_status_display(self, obj):
        if obj.status and obj.status.name:
            return obj.status.name
        return "Müsait"

    def get_status_info(self, obj):
        if not obj.status:
            return {"id": None, "name": "available", "color": STATUS_COLOR_FALLBACKS["available"]}
        normalized_name = (obj.status.name or "available").strip().lower()
        resolved_color = STATUS_COLOR_FALLBACKS.get(normalized_name, obj.status.color or "#6c757d")
        if normalized_name not in STATUS_COLOR_FALLBACKS:
            resolved_color = obj.status.color or "#6c757d"

        return {
            "id": obj.status.id,
            "name": obj.status.name,
            "color": resolved_color
        }

    def get_is_self(self, obj):
        annotated_value = getattr(obj, "is_self", None)
        if isinstance(annotated_value, bool):
            return annotated_value

        request = self.context.get("request")
        if not request or not request.user or not request.user.is_authenticated:
            return False
        request_user_id = str(request.user.id)
        obj_user_id = str(getattr(obj, "user_id", "") or "")
        obj_technician_id = str(getattr(obj, "id", "") or "")
        return request_user_id in {obj_user_id, obj_technician_id}


