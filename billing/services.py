from datetime import datetime, timezone as datetime_timezone
from django.db import transaction
from django.utils import timezone
from . import apple
from .catalog import BUNDLE_ID, PRODUCTS
from .models import AppleBillingAccount, AppleSubscription


def timestamp(value):
    if value is None:
        raise apple.InvalidPurchase('Missing Apple timestamp')
    return datetime.fromtimestamp(value / 1000, tz=datetime_timezone.utc)


def apply_verified(tenant, decoded, status, environment):
    product = PRODUCTS.get(decoded.productId)
    if not product or decoded.bundleId != BUNDLE_ID or decoded.isUpgraded:
        raise apple.InvalidPurchase('Unsupported subscription')
    if environment != 'Production' and not apple.allow_sandbox(tenant):
        raise apple.InvalidPurchase('Sandbox is restricted to test companies')
    if not decoded.originalTransactionId or not decoded.transactionId or not decoded.appAccountToken:
        raise apple.InvalidPurchase('Subscription account binding is missing')
    from tenants.models import Tenant
    with transaction.atomic():
        Tenant.objects.select_for_update().get(pk=tenant.pk)
        account, _ = AppleBillingAccount.objects.get_or_create(tenant=tenant)
        if str(account.app_account_token).lower() != str(decoded.appAccountToken).lower():
            raise apple.InvalidPurchase('Purchase belongs to a different company')
        existing = AppleSubscription.objects.select_for_update().filter(original_transaction_id=decoded.originalTransactionId).first()
        if existing and existing.account_id != account.pk:
            raise apple.InvalidPurchase('Purchase is already assigned')
        signed_at = timestamp(decoded.signedDate)
        if existing and existing.signed_at > signed_at:
            return existing
        values = dict(account=account, transaction_id=decoded.transactionId,
                      product_id=decoded.productId, environment=environment,
                      expires_at=timestamp(decoded.expiresDate), signed_at=signed_at,
                      revoked_at=timestamp(decoded.revocationDate) if decoded.revocationDate else None,
                      status=status)
        subscription, _ = AppleSubscription.objects.update_or_create(
            original_transaction_id=decoded.originalTransactionId, defaults=values)
        return subscription


def verify_purchase(tenant, transaction_id):
    decoded, status, environment = apple.fetch_current(transaction_id, tenant)
    return apply_verified(tenant, decoded, status, environment)


def subscription_info(tenant):
    # An expired/refunded Apple purchase cannot fall back to legacy unlimited access.
    rows = AppleSubscription.objects.filter(account__tenant=tenant).order_by('-expires_at')
    active = rows.filter(status=1, revoked_at__isnull=True, expires_at__gt=timezone.now()).first()
    latest = active or rows.first()
    if not latest:
        return None
    expiry = timezone.localtime(latest.expires_at).date()
    return {'status': 'apple' if active else 'expired', 'is_active': bool(active),
            'plan': latest.product_id, 'ends_at': expiry,
            'days_remaining': max(0, (expiry - timezone.localdate()).days) if active else 0,
            'max_users': 10, 'provider': 'apple'}


def effective_user_limit(tenant):
    if AppleSubscription.objects.filter(account__tenant=tenant).exists():
        return 10
    from config.models import CompanyConfig
    config = CompanyConfig.objects.filter(tenant=tenant).first()
    return int(getattr(config, 'max_users', 0) or 0)
