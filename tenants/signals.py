from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Tenant


@receiver(post_save, sender=Tenant)
def create_tenant_defaults(sender, instance, created, **kwargs):
    if not created:
        return

    instance.start_trial(days=5)

    from accounting.models import Account
    from config.models import CompanyConfig
    from services.models import DEFAULT_SERVICE_STATUSES, PaymentMethod, ServiceStatus
    from technicians.models import TechnicianStatus

    max_users = int((instance.features or {}).get('max_users') or 10)
    company, _ = CompanyConfig.objects.get_or_create(tenant=instance, defaults={'name': instance.app_name or instance.name, 'max_users': max_users})
    Account.objects.get_or_create(tenant=instance, name='Ana Kasa', defaults={'company': company, 'account_type': 'cash'})
    for name, is_default in [('Nakit', True), ('Havale / EFT', False)]:
        PaymentMethod.objects.get_or_create(tenant=instance, name=name, defaults={'is_default': is_default})
    for code, name, color, sort_order, is_terminal in DEFAULT_SERVICE_STATUSES:
        ServiceStatus.objects.get_or_create(tenant=instance, code=code, defaults={'name': name, 'color': color, 'sort_order': sort_order, 'is_default': code == 'new', 'is_terminal': is_terminal})
    for name, color in [('Müsait', '#28a745'), ('İzinli', '#ffc107')]:
        TechnicianStatus.objects.get_or_create(tenant=instance, name=name, defaults={'color': color})