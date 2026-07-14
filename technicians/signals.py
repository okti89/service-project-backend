from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from .services import ensure_technician_profile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_technician_profile(sender, instance, created, **kwargs):
    """Only approved, active technicians receive an operational profile."""
    if (
        created
        and instance.user_type == "technician"
        and instance.approval_status == "approved"
        and instance.is_active
    ):
        ensure_technician_profile(instance)
