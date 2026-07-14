from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from .services import ensure_technician_profile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_technician_profile(sender, instance, created, **kwargs):
    """Yeni kullanıcı oluşturulduğunda otomatik Teknisyen profili + yetkiler oluştur."""
    if created:
        ensure_technician_profile(instance)
