import uuid
from copy import copy
from datetime import timedelta
from unittest.mock import patch
from types import SimpleNamespace
from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError
from appstoreserverlibrary.models.JWSTransactionDecodedPayload import JWSTransactionDecodedPayload
from appstoreserverlibrary.models.Environment import Environment
from appstoreserverlibrary.api_client import APIException
from tenants.models import Tenant
from . import apple
from .models import AppleBillingAccount, AppleSubscription, AppleNotification
from .services import apply_verified, verify_purchase, effective_user_limit
from .catalog import BUNDLE_ID, PRODUCTS

class AppleBillingTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Billing Test', code='billing-demo')
        self.account = AppleBillingAccount.objects.create(tenant=self.tenant)
        now = timezone.now()
        self.decoded = JWSTransactionDecodedPayload(originalTransactionId='100001', transactionId='100002',
            productId=next(iter(PRODUCTS)), bundleId=BUNDLE_ID, appAccountToken=str(self.account.app_account_token),
            signedDate=int(now.timestamp()*1000), expiresDate=int((now+timedelta(days=30)).timestamp()*1000))
        self.admin = get_user_model().objects.create_user(email='owner@example.invalid', tenant=self.tenant,
            user_type='admin', approval_status='approved')
        self.client = APIClient(); self.client.force_authenticate(self.admin)

    def apply(self, decoded=None, status=1, environment='Production'):
        return apply_verified(self.tenant, decoded or self.decoded, status, environment)

    def test_verified_purchase_and_repeat_are_idempotent(self):
        self.apply(); self.apply()
        self.assertEqual(AppleSubscription.objects.count(), 1)
        self.assertEqual(self.tenant.subscription_info()['max_users'], 10)
        self.assertTrue(self.tenant.subscription_info()['is_active'])

    def test_product_bundle_and_company_binding_rejected(self):
        for field, value in [('productId', 'foreign.product'), ('bundleId', 'foreign.app'), ('appAccountToken', str(uuid.uuid4())), ('appAccountToken', None), ('isUpgraded', True)]:
            with self.subTest(field=field):
                decoded = copy(self.decoded); setattr(decoded, field, value)
                with self.assertRaises(apple.InvalidPurchase): self.apply(decoded)
        self.assertEqual(AppleSubscription.objects.count(), 0)

    def test_other_tenant_cannot_claim_original_purchase(self):
        self.apply()
        other = Tenant.objects.create(name='Other', code='other-company')
        account = AppleBillingAccount.objects.create(tenant=other)
        decoded = copy(self.decoded); decoded.appAccountToken = str(account.app_account_token)
        with self.assertRaises(apple.InvalidPurchase): apply_verified(other, decoded, 1, 'Production')

    def test_sandbox_cannot_unlock_real_company(self):
        self.tenant.code = 'real-company'; self.tenant.save()
        with self.assertRaises(apple.InvalidPurchase): self.apply(environment='Sandbox')

    def test_sandbox_allowed_only_for_named_demo(self):
        self.assertTrue(self.apply(environment='Sandbox').is_active)

    def test_expiry_refund_and_retry_status_do_not_grant_access(self):
        self.tenant.memberships.update(renewal_date=timezone.localdate()-timedelta(days=1))
        for status in [2, 3, 4, 5]:
            with self.subTest(status=status):
                self.apply(status=status)
                self.assertFalse(self.tenant.subscription_info()['is_active'])
        decoded = copy(self.decoded); decoded.revocationDate = decoded.signedDate
        self.apply(decoded)
        self.assertFalse(self.tenant.subscription_info()['is_active'])
        decoded = copy(self.decoded); decoded.expiresDate = decoded.signedDate - 1000
        self.apply(decoded)
        self.assertFalse(self.tenant.subscription_info()['is_active'])

    def test_cancellation_keeps_paid_term_access(self):
        # Status 1 with future expiry remains active even when auto-renewal is off.
        self.assertTrue(self.apply().is_active)

    def test_older_notification_cannot_regrant_revoked_access(self):
        self.tenant.memberships.update(renewal_date=timezone.localdate()-timedelta(days=1))
        revoked = copy(self.decoded); revoked.revocationDate = revoked.signedDate; revoked.signedDate += 1000
        self.apply(revoked, status=5)
        self.apply(self.decoded)
        self.assertFalse(self.tenant.subscription_info()['is_active'])

    def test_user_limit_counts_manager_and_reactivation(self):
        self.apply()
        User = get_user_model()
        for index in range(9):
            User.objects.create_user(email=f'worker{index}@example.invalid', tenant=self.tenant)
        with self.assertRaises(ValidationError):
            User.objects.create_user(email='eleven@example.invalid', tenant=self.tenant)
        dormant = User.objects.create_user(email='inactive@example.invalid', tenant=self.tenant, is_active=False)
        dormant.is_active = True
        with self.assertRaises(ValidationError): dormant.save(update_fields=['is_active'])
        self.assertEqual(User.objects.filter(tenant=self.tenant, is_active=True).count(), 10)

    def test_manual_membership_unchanged_without_apple_purchase(self):
        self.assertEqual(self.tenant.subscription_info()['status'], 'trial')
        self.assertEqual(effective_user_limit(self.tenant), 5)

    def test_expired_admin_can_read_profile_and_verify(self):
        self.tenant.memberships.update(renewal_date=timezone.localdate()-timedelta(days=1))
        from rest_framework.authtoken.models import Token
        token, _ = Token.objects.get_or_create(user=self.admin)
        self.client.force_authenticate(user=None)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        self.assertEqual(self.client.get('/api/services/admin-services/').status_code, 403)
        response = self.client.get('/api/billing/apple/profile/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['can_purchase'])
        with patch('billing.apple.fetch_current', return_value=(self.decoded, 1, 'Production')):
            response = self.client.post('/api/billing/apple/verify/', {'transaction_id': '100002'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['active'])

    def test_technician_cannot_purchase_or_obtain_binding_token(self):
        self.admin.user_type = 'technician'; self.admin.save(update_fields=['user_type'])
        response = self.client.get('/api/billing/apple/profile/')
        self.assertFalse(response.data['can_purchase']); self.assertIsNone(response.data['app_account_token'])
        self.assertEqual(self.client.post('/api/billing/apple/verify/', {'transaction_id': '100002'}).status_code, 403)

    def test_client_payload_is_not_trusted(self):
        with patch('billing.apple.fetch_current', side_effect=apple.InvalidPurchase('forged')):
            response = self.client.post('/api/billing/apple/verify/', {'transaction_id': '100002', 'active': True, 'productId': self.decoded.productId})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AppleSubscription.objects.count(), 0)

    def test_notification_deduplication(self):
        notice = SimpleNamespace(notificationUUID=str(uuid.uuid4()))
        with patch('billing.apple.decode_notification', return_value=(notice, self.decoded, 'Production')), patch('billing.views.verify_purchase', return_value=self.apply()) as verify:
            for _ in range(2):
                response = self.client.post('/api/billing/apple/notifications/', {'signedPayload': 'signed'})
                self.assertEqual(response.status_code, 200)
            self.assertEqual(verify.call_count, 1)
        self.assertEqual(AppleNotification.objects.count(), 1)

    def test_failed_notification_remains_retryable(self):
        notice = SimpleNamespace(notificationUUID=str(uuid.uuid4()))
        with patch('billing.apple.decode_notification', return_value=(notice, self.decoded, 'Production')), patch('billing.views.verify_purchase', side_effect=apple.StoreUnavailable()):
            response = self.client.post('/api/billing/apple/notifications/', {'signedPayload': 'signed'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(AppleNotification.objects.count(), 0)

    def test_missing_server_key_fails_closed(self):
        apple.clients.cache_clear()
        with override_settings(APPLE_IAP_PRIVATE_KEY_PATH='', APPLE_IAP_KEY_ID='', APPLE_IAP_ISSUER_ID=''):
            with self.assertRaises(apple.StoreUnavailable): verify_purchase(self.tenant, '100002')

    def test_tampered_notification_signature_is_rejected(self):
        verifier = SimpleNamespace(verify_and_decode_notification=lambda _: (_ for _ in ()).throw(ValueError('invalid signature')))
        with patch('billing.apple.clients', return_value=(None, verifier)):
            with self.assertRaises(apple.InvalidPurchase): apple.decode_notification('forged')

    def test_sandbox_fallback_only_on_production_transaction_not_found(self):
        client = SimpleNamespace(get_transaction_info=lambda _: (_ for _ in ()).throw(APIException(404, 4040010)))
        with patch('billing.apple.clients', return_value=(client, None)) as clients:
            with self.assertRaises(apple.StoreUnavailable): verify_purchase(self.tenant, '100002')
            self.assertEqual(clients.call_count, 2)
        client = SimpleNamespace(get_transaction_info=lambda _: (_ for _ in ()).throw(APIException(500, 5000001)))
        with patch('billing.apple.clients', return_value=(client, None)) as clients:
            with self.assertRaises(apple.StoreUnavailable): verify_purchase(self.tenant, '100002')
            self.assertEqual(clients.call_count, 1)

    def test_sandbox_expiry_does_not_destroy_existing_demo_access(self):
        self.apply(status=2, environment='Sandbox')
        self.assertTrue(self.tenant.subscription_info()['is_active'])
        self.assertEqual(self.tenant.subscription_info()['status'], 'trial')

    def test_missing_server_key_disables_purchase_profile(self):
        apple.clients.cache_clear()
        with override_settings(APPLE_IAP_PRIVATE_KEY_PATH='', APPLE_IAP_KEY_ID='', APPLE_IAP_ISSUER_ID=''):
            self.assertFalse(self.client.get('/api/billing/apple/profile/').data['store_ready'])

    def test_apple_test_notification_is_acknowledged_without_entitlement(self):
        with patch('billing.apple.decode_notification', return_value=(SimpleNamespace(notificationUUID=str(uuid.uuid4())), None, 'Production')):
            response = self.client.post('/api/billing/apple/notifications/', {'signedPayload': 'signed'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AppleSubscription.objects.count(), 0)

    def test_registration_uses_apple_limit_instead_of_old_company_limit(self):
        self.apply()
        from accounts.serializers import UserCreateSerializer
        for index in range(4):
            get_user_model().objects.create_user(email=f'existing{index}@example.invalid', tenant=self.tenant)
        request = SimpleNamespace(user=self.admin)
        serializer = UserCreateSerializer(data={'email': 'sixth@example.invalid', 'password': 'test-only-pass'}, context={'request': request})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        self.assertEqual(get_user_model().objects.filter(tenant=self.tenant).count(), 6)

    def test_existing_over_limit_company_cannot_start_purchase_but_can_restore(self):
        from config.models import CompanyConfig
        CompanyConfig.objects.filter(tenant=self.tenant).update(max_users=20)
        for index in range(10):
            get_user_model().objects.create_user(email=f'over{index}@example.invalid', tenant=self.tenant)
        profile = self.client.get('/api/billing/apple/profile/').data
        self.assertFalse(profile['can_purchase'])
        self.assertTrue(profile['can_restore'])
        self.assertTrue(profile['purchase_block_reason'])
