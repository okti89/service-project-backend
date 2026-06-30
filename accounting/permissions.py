from rest_framework import permissions


class IsAccountingManager(permissions.BasePermission):
    message = "Muhasebe yonetim yetkiniz yok."

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        role = getattr(user, "user_type", None)

        if role == "admin" or user.is_superuser:
            return True

        if role != "technician":
            return False

        profile = getattr(user, "technician_profile", None)
        perms = getattr(profile, "permissions", None) if profile else None

        if not perms:
            return False

        return bool(getattr(perms, "can_manage_accounting", False))
