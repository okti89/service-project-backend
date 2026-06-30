from rest_framework import permissions


class IsServiceManager(permissions.BasePermission):

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if getattr(user, "user_type", None) == "admin":
            return True

        if getattr(user, "user_type", None) != "technician":
            return False

        technician_profile = getattr(user, "technician_profile", None)
        if not technician_profile:
            return False

        permission_obj = getattr(technician_profile, "permissions", None)
        if not permission_obj:
            return False

        if request.method in permissions.SAFE_METHODS:
            return bool(
                getattr(permission_obj, "can_manage_services", False)
                or getattr(permission_obj, "can_view_all_services", False)
            )

        return bool(getattr(permission_obj, "can_manage_services", False))
