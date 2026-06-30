from rest_framework import permissions


class IsSettingsManager(permissions.BasePermission):

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        role = getattr(user, "user_type", None)

        # 🔥 ADMIN FULL ACCESS (TEK NOKTA)
        if role == "admin" or user.is_superuser:
            return True

        # 🔴 SETTINGS READ EVEN RESTRICTED (istersen kaldırabilirsin)
        if request.method in permissions.SAFE_METHODS:
            return role in ["admin", "technician"]

        # 🔵 TECHNICIAN PERMISSION CHECK
        if role == "technician":
            profile = getattr(user, "technician_profile", None)
            perms = getattr(profile, "permissions", None)

            if not perms:
                return False

            return bool(perms.can_manage_settings)

        return False