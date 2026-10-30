from datetime import datetime, timezone as datetime_timezone
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from . import revenuecat
from .catalog import PRODUCTS
from .models import BillingAccount, CompanySubscription


def parse_time(value):
    result = parse_datetime(value) if isinstance(value, str) else None
    if result is None or timezone.is_naive(result):
        raise revenuecat.InvalidStoreData('Missing or invalid timestamp')
    return result


def sync_subscription(tenant):
    account, _ = BillingAccount.objects.get_or_create(tenant=tenant)
    # The customer ID comes from the authenticated tenant, never the request body.
    payload = revenuecat.fetch_customer(account.app_user_id)
    subscriber = payload['subscriber']
    if subscriber.get('original_app_user_id') != str(account.app_user_id):
        raise revenuecat.InvalidStoreData('Customer identity is not bound to this company')
    request_ms = payload.get('request_date_ms')
    if not isinstance(request_ms, (int, float)) or isinstance(request_ms, bool):
        raise revenuecat.InvalidStoreData('Missing verification time')
    try:
        checked_at = datetime.fromtimestamp(request_ms / 1000, tz=datetime_timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise revenuecat.InvalidStoreData('Invalid verification time') from exc
    entitlements = subscriber.get('entitlements')
    subscriptions = subscriber.get('subscriptions')
    if not isinstance(entitlements, dict) or not isinstance(subscriptions, dict):
        raise revenuecat.InvalidStoreData('Missing subscription state')
    entitlement = entitlements.get(settings.REVENUECAT_ENTITLEMENT_ID)
    values = None
    if entitlement:
        if not isinstance(entitlement, dict):
            raise revenuecat.InvalidStoreData('Malformed entitlement')
        product_id = entitlement.get('product_identifier')
        if not isinstance(product_id, str):
            raise revenuecat.InvalidStoreData('Malformed product identifier')
        product = subscriptions.get(product_id)
        if product_id not in PRODUCTS or not isinstance(product, dict) or product.get('store') != 'app_store':
            raise revenuecat.InvalidStoreData('Unsupported product or store')
        sandbox = product.get('is_sandbox')
        if not isinstance(sandbox, bool):
            raise revenuecat.InvalidStoreData('Missing store environment')
        if sandbox and tenant.code not in getattr(settings, 'REVENUECAT_SANDBOX_TENANTS', []):
            raise revenuecat.InvalidStoreData('Sandbox is restricted to demo companies')
        expiry = min(parse_time(entitlement.get('expires_date')), parse_time(product.get('expires_date')))
        values = dict(product_id=product_id, store='app_store', environment='Sandbox' if sandbox else 'Production',
                      expires_at=expiry, active=product.get('gives_access') is True and not bool(product.get('refunded_at')) and expiry > timezone.now(),
                      verified_at=checked_at)
    from tenants.models import Tenant
    with transaction.atomic():
        Tenant.objects.select_for_update().get(pk=tenant.pk)
        previous = CompanySubscription.objects.select_for_update().filter(account=account).first()
        if previous and previous.verified_at > checked_at:
            return previous
        if values:
            row, _ = CompanySubscription.objects.update_or_create(account=account, defaults=values)
            return row
        # An empty customer must not invalidate legacy/manual access before any purchase.
        if previous:
            previous.active = False
            previous.verified_at = checked_at
            previous.save(update_fields=['active', 'verified_at', 'updated_at'])
        return previous


def subscription_info(tenant):
    row = CompanySubscription.objects.filter(account__tenant=tenant).first()
    if not row:
        return None
    expiry = timezone.localtime(row.expires_at).date()
    return {'status': 'revenuecat' if row.is_active else 'expired', 'is_active': row.is_active,
            'plan': row.product_id, 'ends_at': expiry,
            'days_remaining': max(0, (expiry - timezone.localdate()).days) if row.is_active else 0,
            'max_users': 10, 'provider': 'revenuecat'}


def effective_user_limit(tenant):
    if CompanySubscription.objects.filter(account__tenant=tenant).exists():
        return 10
    from config.models import CompanyConfig
    config = CompanyConfig.objects.filter(tenant=tenant).first()
    return int(getattr(config, 'max_users', 0) or 0)
