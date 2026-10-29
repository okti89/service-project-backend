import hmac
from django.conf import settings
from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.decorators import api_view, permission_classes, authentication_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from . import revenuecat
from .catalog import PRODUCTS
from .models import BillingAccount, BillingEvent
from .services import sync_subscription

class BillingThrottle(UserRateThrottle):
    rate = '30/minute'

def can_manage(user):
    return bool(user.is_active and user.approval_status == 'approved' and
                user.user_type == 'admin' and user.tenant and user.tenant.is_active)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def profile(request):
    allowed = can_manage(request.user)
    customer_id = None
    if allowed:
        account, _ = BillingAccount.objects.get_or_create(tenant=request.user.tenant)
        customer_id = str(account.app_user_id)
    within_limit = bool(allowed and request.user.tenant.users.filter(is_active=True).count() <= 10)
    return Response({'can_purchase': allowed and within_limit, 'can_restore': allowed,
        'purchase_block_reason': 'Önce aktif kullanıcı sayısını yönetici dahil 10 veya altına indirin.' if allowed and not within_limit else None,
        'store_ready': allowed and revenuecat.is_configured(), 'app_user_id': customer_id,
        'public_sdk_key': settings.REVENUECAT_APPLE_PUBLIC_SDK_KEY if allowed else None,
        'entitlement_id': settings.REVENUECAT_ENTITLEMENT_ID, 'products': list(PRODUCTS), 'max_users': 10,
        'subscription': request.user.tenant.subscription_info() if request.user.tenant else None})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([BillingThrottle])
def sync(request):
    if not can_manage(request.user):
        return Response({'detail': 'Aboneliği yalnızca onaylı firma yöneticisi yönetebilir.'}, status=403)
    try:
        row = sync_subscription(request.user.tenant)
    except (revenuecat.StoreUnavailable, revenuecat.InvalidStoreData):
        return Response({'detail': 'Abonelik sunucuda doğrulanamadı. Satın alımları geri yükleyerek yeniden deneyin.'}, status=503)
    return Response({'verified': True, 'active': bool(row and row.is_active),
                     'subscription': request.user.tenant.subscription_info()})

@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def webhook(request):
    secret = getattr(settings, 'REVENUECAT_WEBHOOK_AUTHORIZATION', '')
    if not secret:
        return Response(status=503)
    if not hmac.compare_digest(request.headers.get('Authorization', ''), secret):
        return Response(status=401)
    event = request.data.get('event')
    if not isinstance(event, dict):
        return Response(status=400)
    event_id = event.get('id')
    if not isinstance(event_id, str) or not event_id or len(event_id) > 128:
        return Response(status=400)
    if event.get('type') == 'TEST':
        return Response(status=200)
    ids = [event.get('app_user_id')]
    if event.get('type') == 'TRANSFER':
        for field in ('transferred_from', 'transferred_to'):
            values = event.get(field, [])
            if not isinstance(values, list) or len(values) > 40:
                return Response(status=400)
            ids.extend(values)
    try:
        from uuid import UUID
        parsed_ids = {UUID(value) for value in ids if isinstance(value, str) and not value.startswith('$RCAnonymousID:')}
    except ValueError:
        return Response(status=400)
    accounts = list(BillingAccount.objects.select_related('tenant').filter(app_user_id__in=parsed_ids).order_by('tenant_id'))
    # Authenticate the event, but grant/revoke only after fetching current server state.
    try:
        with transaction.atomic():
            _, created = BillingEvent.objects.get_or_create(event_id=event_id)
            if created:
                for account in accounts:
                    sync_subscription(account.tenant)
        return Response(status=200)
    except (revenuecat.StoreUnavailable, revenuecat.InvalidStoreData):
        return Response(status=503)
