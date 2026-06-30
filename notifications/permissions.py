from rest_framework import permissions

class IsNotificationManager(permissions.BasePermission):

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        # Admin full access
        if user.is_superuser or getattr(user, "user_type", None) == "admin":
            return True

        # Read-only izin (isteğe bağlı daraltabilirsin)
        if request.method in permissions.SAFE_METHODS:
            return True

        # Technician kontrol
        if getattr(user, "user_type", None) == "technician":
            technician_profile = getattr(user, "technician_profile", None)

            if not technician_profile:
                return False

            return getattr(
                technician_profile.permissions,
                "can_manage_notifications",
                False
            )

        return False