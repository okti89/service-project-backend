from django.db import transaction

from .models import Technician, TechnicianPermissions


@transaction.atomic
def ensure_technician_profile(user):
    """Create the technician identity and default permissions exactly once."""
    if not user or user.user_type != "technician":
        return None

    technician, _ = Technician.objects.get_or_create(
        user=user,
        defaults={"tenant": user.tenant},
    )
    if not technician.tenant_id and user.tenant_id:
        technician.tenant = user.tenant
        technician.save(update_fields=["tenant"])

    permissions, _ = TechnicianPermissions.objects.get_or_create(
        technician=technician,
        defaults={"tenant": user.tenant},
    )
    if not permissions.tenant_id and user.tenant_id:
        permissions.tenant = user.tenant
        permissions.save(update_fields=["tenant"])

    return technician