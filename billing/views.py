from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from . import apple
from .catalog import PRODUCTS
from .models import AppleBillingAccount, AppleNotification
from .services import verify_purchase

class BillingThrottle(UserRateThrottle):
    rate = '30/minute'

def can_purchase(user):
    return bool(user.is_active and user.approval_status == 'approved' and
                user.user_type == 'admin' and user.tenant and user.tenant.is_active)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def profile(request):
    allowed = can_purchase(request.user)
    token = None
    if allowed:
        account, _ = AppleBillingAccount.objects.get_or_create(tenant=request.user.tenant)
        token = str(account.app_account_token)
    store_ready = False
    if allowed:
        try:
            from appstoreserverlibrary.models.Environment import Environment
            apple.clients(Environment.PRODUCTION)
            store_ready = True
        except apple.StoreUnavailable:
            pass
    within_limit = bool(allowed and request.user.tenant.users.filter(is_active=True).count() <= 10)
    return Response({'can_purchase': allowed and within_limit, 'can_restore': allowed,
                     'purchase_block_reason': 'Önce aktif kullanıcı sayısını yönetici dahil 10 veya altına indirin.' if allowed and not within_limit else None,
                     'store_ready': store_ready, 'app_account_token': token,
                     'products': list(PRODUCTS), 'max_users': 10,
                     'subscription': request.user.tenant.subscription_info() if request.user.tenant else None})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([BillingThrottle])
def verify(request):
    if not can_purchase(request.user):
        return Response({'detail': 'Aboneliği yalnızca onaylı firma yöneticisi yönetebilir.'}, status=403)
    transaction_id = request.data.get('transaction_id')
    if not isinstance(transaction_id, str) or not transaction_id.isdigit() or len(transaction_id) > 128:
        return Response({'detail': 'Geçersiz işlem numarası.'}, status=400)
    try:
        subscription = verify_purchase(request.user.tenant, transaction_id)
    except apple.StoreUnavailable:
        return Response({'detail': 'Apple doğrulaması şu anda tamamlanamadı. Yeniden deneyin.'}, status=503)
    except apple.InvalidPurchase:
        return Response({'detail': 'Bu satın alma firma için doğrulanamadı.'}, status=400)
    return Response({'verified': True, 'active': subscription.is_active,
                     'subscription': request.user.tenant.subscription_info()})

@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def notifications(request):
    payload = request.data.get('signedPayload')
    if not isinstance(payload, str) or len(payload) > 100000:
        return Response(status=400)
    try:
        notice, decoded, environment = apple.decode_notification(payload)
        if not notice.notificationUUID:
            return Response(status=400)
        if decoded is None:
            return Response(status=200)
        account = AppleBillingAccount.objects.select_related('tenant').filter(app_account_token=decoded.appAccountToken).first()
        if not account or (environment != 'Production' and not apple.allow_sandbox(account.tenant)):
            return Response(status=400)
        # Serialize duplicate deliveries, acknowledge only after current status is saved.
        with transaction.atomic():
            _, created = AppleNotification.objects.get_or_create(notification_id=notice.notificationUUID)
            if created:
                verify_purchase(account.tenant, decoded.transactionId)
        return Response(status=200)
    except apple.StoreUnavailable:
        return Response(status=503)
    except (apple.InvalidPurchase, ValueError, DjangoValidationError):
        return Response(status=400)
