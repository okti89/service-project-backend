from rest_framework import permissions


class IsReportManager(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        # Admin full access
        if getattr(user, "user_type", None) == "admin":
            return True

        # Technician kontrolü
        if getattr(user, "user_type", None) != "technician":
            return False

        technician_profile = getattr(user, "technician_profile", None)
        if not technician_profile:
            return False

        permissions_obj = getattr(technician_profile, "permissions", None)
        if not permissions_obj:
            return False

        return bool(getattr(permissions_obj, "can_manage_reports", False))
