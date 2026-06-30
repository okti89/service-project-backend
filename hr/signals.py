from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction

from .models import Payroll, PayrollComponent, PayrollTemplate


@receiver(post_save, sender=Payroll)
def payroll_created(sender, instance, created, **kwargs):
    if not created:
        return

    tenant = instance.tenant

    if not tenant:
        return

    templates = PayrollTemplate.objects.filter(
        is_active=True,
        tenant=tenant
    )

    existing = set(
        instance.components.values_list("name", "type")
    )

    components = []

    for t in templates:
        if (t.name, t.type) in existing:
            continue

        components.append(
            PayrollComponent(
                payroll=instance,
                tenant=tenant,
                name=t.name,
                amount=t.default_amount or 0,
                type=t.type,
                is_manual=False
            )
        )

    if not components:
        return

    with transaction.atomic():
        PayrollComponent.objects.bulk_create(components)
