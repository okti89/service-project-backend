from rest_framework import permissions

class IsGlobalSearchManager(permissions.BasePermission):

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        # Admin full access
        if user.is_superuser or getattr(user, "user_type", None) == "admin":
            return True

        # Technician kontrol
        if getattr(user, "user_type", None) == "technician":
            technician_profile = getattr(user, "technician_profile", None)

            if not technician_profile:
                return False

            permission_obj = getattr(technician_profile, "permissions", None)
            return request.method in permissions.SAFE_METHODS and getattr(
                permission_obj,
                "can_use_global_search",
                False
            )

        return False
