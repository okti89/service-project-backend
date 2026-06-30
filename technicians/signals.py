from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from .models import Technician, TechnicianPermissions


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_technician_profile(sender, instance, created, **kwargs):
    """Yeni kullanıcı oluşturulduğunda otomatik Teknisyen profili + yetkiler oluştur."""
    if created:
        tech, tech_created = Technician.objects.get_or_create(user=instance)
        if tech_created:
            TechnicianPermissions.objects.get_or_create(technician=tech)
