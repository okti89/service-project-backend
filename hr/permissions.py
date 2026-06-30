from rest_framework import permissions


class IsHRManager(permissions.BasePermission):

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        # Super admin full access
        if user.is_superuser:
            return True

        user_type = getattr(user, "user_type", None)

        # ADMIN full access
        if user_type == "admin":
            return True

        technician_profile = getattr(user, "technician_profile", None)

        is_hr_manager = (
            technician_profile
            and getattr(technician_profile.permissions, "can_manage_hr", False)
        )


        return is_hr_manager