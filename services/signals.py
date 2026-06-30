from decimal import Decimal
import calendar

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from accounting.models import Account, Transaction, TransactionCategory
from .models import ServiceOperations, ServicePayment

AUTO_SERVICE_WORK_INCOME_CATEGORY = "Servis Islem Geliri"
AUTO_SERVICE_COLLECTION_INCOME_CATEGORY = "Servis Tahsilat Geliri"


def _get_service_items_total(service):
    total = Decimal('0.00')
    for item in service.items.all():
        if item.total_price is not None:
            total += Decimal(str(item.total_price))
    return total


def _get_service_payments_total(service):
    total = Decimal('0.00')
    for payment in service.payments.all():
        if payment.amount is not None:
            total += Decimal(str(payment.amount))
    return total


def _resolve_tenant(service):
    return getattr(service, 'tenant', None) or getattr(getattr(service, 'customer', None), 'tenant', None)


def _resolve_default_account(service):
    tenant = _resolve_tenant(service)
    if not tenant:
        return None
    return Account.objects.filter(tenant=tenant).order_by('created_at').first()


def _resolve_or_create_income_category(service, category_name):
    tenant = _resolve_tenant(service)
    if not tenant:
        return None
    category, _ = TransactionCategory.objects.get_or_create(
        tenant=tenant,
        name=category_name,
        type='income',
    )
    return category


def _sync_service_transaction_by_category(service, amount, category_name):
    tenant = _resolve_tenant(service)
    if not tenant:
        return

    category = _resolve_or_create_income_category(service, category_name)
    account = _resolve_default_account(service)
    if not category or not account:
        return

    income_qs = Transaction.objects.filter(
        tenant=tenant,
        service=service,
        transaction_type='income',
        category=category,
    ).order_by('created_at')

    if amount <= 0:
        income_qs.delete()
        return

    tx = income_qs.first()
    if tx is None:
        tx = Transaction(
            tenant=tenant,
            service=service,
            transaction_type='income',
            category=category,
            account=account,
        )
    else:
        tx.account = account

    tx.amount = amount
    tx.date = timezone.now()
    tx.description = f"Servis #{service.receipt_number or ''} {category_name.lower()}"
    # Keep under accounting.Transaction.receipt_number max_length=50.
    tx.receipt_number = f"SRV:{service.id.hex[:12]}:{category.id.hex[:12]}"
    tx.save()

    income_qs.exclude(pk=tx.pk).delete()


def sync_service_income_transaction(service):
    work_amount = _get_service_items_total(service)
    _sync_service_transaction_by_category(service, work_amount, AUTO_SERVICE_WORK_INCOME_CATEGORY)


@receiver(post_save, sender=ServiceOperations)
def handle_service_operation_save(sender, instance, created, **kwargs):
    sync_service_income_transaction(instance.service)


@receiver(post_delete, sender=ServiceOperations)
def handle_service_operation_delete(sender, instance, **kwargs):
    sync_service_income_transaction(instance.service)


# ServicePayment muhasebe senkronu model tarafinda odeme-satiri bazli yapiliyor.


def add_months(sourcedate, months):
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return sourcedate.replace(year=year, month=month, day=day)
