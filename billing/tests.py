from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch, Mock
from django.test import TestCase, override_settings
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError
from tenants.models import Tenant
from . import revenuecat
from .models import BillingAccount, CompanySubscription, BillingEvent
from .services import sync_subscription, effective_user_limit
from .catalog import PRODUCTS

class RevenueCatBillingTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Billing Test', code='billing-demo')
        self.account = BillingAccount.objects.create(tenant=self.tenant)
        now = timezone.now(); self.expiry = now + timedelta(days=30)
        self.product_id = next(iter(PRODUCTS))
        self.payload = {'request_date_ms': int(now.timestamp()*1000), 'subscriber': {
            'original_app_user_id': str(self.account.app_user_id),
            'entitlements': {'company_10': {'product_identifier': self.product_id, 'expires_date': self.expiry.isoformat()}},
            'subscriptions': {self.product_id: {'store': 'app_store', 'is_sandbox': False, 'gives_access': True, 'expires_date': self.expiry.isoformat(), 'refunded_at': None, 'unsubscribe_detected_at': None}}}}
        self.admin = get_user_model().objects.create_user(email='owner@example.invalid', tenant=self.tenant, user_type='admin', approval_status='approved')
        self.client = APIClient(); self.client.force_authenticate(self.admin)

    def synchronize(self, payload=None):
        with patch('billing.revenuecat.fetch_customer', return_value=payload or self.payload):
            return sync_subscription(self.tenant)

    def empty(self):
        payload = deepcopy(self.payload)
        payload['subscriber']['entitlements'] = {}; payload['subscriber']['subscriptions'] = {}
        return payload

    def expire_manual_membership(self):
        self.tenant.memberships.update(renewal_date=timezone.localdate()-timedelta(days=1))

    def test_server_subscription_sync_is_idempotent_and_caps_ten_users(self):
        self.synchronize(); self.synchronize()
        self.assertEqual(CompanySubscription.objects.count(), 1)
        self.assertEqual(self.tenant.subscription_info()['max_users'], 10)
        self.assertTrue(self.tenant.subscription_info()['is_active'])

    def test_foreign_company_identity_cannot_grant_access(self):
        payload = deepcopy(self.payload); payload['subscriber']['original_app_user_id'] = 'foreign-company'
        with self.assertRaises(revenuecat.InvalidStoreData): self.synchronize(payload)
        self.assertFalse(CompanySubscription.objects.exists())

    def test_unsupported_product_and_store_are_rejected(self):
        payload = deepcopy(self.payload); payload['subscriber']['subscriptions'][self.product_id]['store'] = 'test_store'
        with self.assertRaises(revenuecat.InvalidStoreData): self.synchronize(payload)
        payload = deepcopy(self.payload); payload['subscriber']['entitlements']['company_10']['product_identifier'] = 'foreign.product'
        with self.assertRaises(revenuecat.InvalidStoreData): self.synchronize(payload)

    def test_sandbox_is_restricted_to_named_demo_tenants(self):
        payload = deepcopy(self.payload); payload['subscriber']['subscriptions'][self.product_id]['is_sandbox'] = True
        self.assertTrue(self.synchronize(payload).is_active)
        self.tenant.code = 'real-company'; self.tenant.save()
        with self.assertRaises(revenuecat.InvalidStoreData): self.synchronize(payload)

    def test_missing_environment_is_rejected(self):
        del self.payload['subscriber']['subscriptions'][self.product_id]['is_sandbox']
        with self.assertRaises(revenuecat.InvalidStoreData): self.synchronize()

    def test_cancellation_preserves_the_paid_term(self):
        self.payload['subscriber']['subscriptions'][self.product_id]['unsubscribe_detected_at'] = timezone.now().isoformat()
        self.assertTrue(self.synchronize().is_active)

    def test_refund_revokes_even_before_paid_expiry(self):
        self.expire_manual_membership()
        self.payload['subscriber']['subscriptions'][self.product_id]['refunded_at'] = timezone.now().isoformat()
        self.assertFalse(self.synchronize().is_active)
        self.assertFalse(self.tenant.subscription_info()['is_active'])

    def test_expiry_and_removed_entitlement_revoke_access(self):
        self.expire_manual_membership(); self.synchronize()
        self.assertFalse(self.synchronize(self.empty()).is_active)
        self.assertFalse(self.tenant.subscription_info()['is_active'])
        past = (timezone.now()-timedelta(seconds=1)).isoformat()
        self.payload['subscriber']['entitlements']['company_10']['expires_date'] = past
        self.assertFalse(self.synchronize().is_active)

    def test_no_purchase_does_not_lock_legacy_or_demo_membership(self):
        self.assertIsNone(self.synchronize(self.empty()))
        self.assertFalse(CompanySubscription.objects.exists())
        self.assertTrue(self.tenant.subscription_info()['is_active'])
        self.assertEqual(effective_user_limit(self.tenant), 5)

    def test_demo_membership_survives_sandbox_expiry(self):
        self.synchronize(); self.synchronize(self.empty())
        self.assertEqual(self.tenant.subscription_info()['status'], 'trial')
        self.assertTrue(self.tenant.subscription_info()['is_active'])

    def test_stale_response_cannot_restore_a_revoked_subscription(self):
        self.synchronize()
        current = self.empty(); current['request_date_ms'] += 1000
        self.synchronize(current); self.synchronize(self.payload)
        self.assertFalse(CompanySubscription.objects.get().is_active)

    def test_invalid_dates_fail_closed(self):
        for value in [None, 'nonsense', '2026-10-29T12:00:00']:
            with self.subTest(value=value):
                payload = deepcopy(self.payload); payload['subscriber']['entitlements']['company_10']['expires_date'] = value
                with self.assertRaises(revenuecat.InvalidStoreData): self.synchronize(payload)

    def test_user_limit_counts_manager_and_reactivation(self):
        self.synchronize(); User = get_user_model()
        for index in range(9): User.objects.create_user(email=f'worker{index}@example.invalid', tenant=self.tenant)
        with self.assertRaises(ValidationError): User.objects.create_user(email='eleven@example.invalid', tenant=self.tenant)
        dormant = User.objects.create_user(email='inactive@example.invalid', tenant=self.tenant, is_active=False)
        dormant.is_active = True
        with self.assertRaises(ValidationError): dormant.save(update_fields=['is_active'])
        self.assertEqual(User.objects.filter(tenant=self.tenant, is_active=True).count(), 10)

    def test_registration_uses_apple_plan_limit_not_old_company_config(self):
        self.synchronize()
        from accounts.serializers import UserCreateSerializer
        for index in range(4): get_user_model().objects.create_user(email=f'existing{index}@example.invalid', tenant=self.tenant)
        serializer = UserCreateSerializer(data={'email': 'sixth@example.invalid', 'password': 'test-only-pass'}, context={'request': SimpleNamespace(user=self.admin)})
        self.assertTrue(serializer.is_valid(), serializer.errors); serializer.save()

    def test_expired_admin_can_sync_through_real_token_middleware(self):
        self.expire_manual_membership()
        from rest_framework.authtoken.models import Token
        token, _ = Token.objects.get_or_create(user=self.admin)
        self.client.force_authenticate(user=None); self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        self.assertEqual(self.client.get('/api/services/admin-services/').status_code, 403)
        profile = self.client.get('/api/billing/revenuecat/profile/')
        self.assertEqual(profile.status_code, 200); self.assertTrue(profile.data['can_purchase'])
        with patch('billing.revenuecat.fetch_customer', return_value=self.payload):
            response = self.client.post('/api/billing/revenuecat/sync/', {'app_user_id': 'attacker-controlled', 'active': True})
        self.assertEqual(response.status_code, 200); self.assertTrue(response.data['active'])

    def test_technician_cannot_obtain_billing_identity_or_manage_subscription(self):
        self.admin.user_type = 'technician'; self.admin.save(update_fields=['user_type'])
        profile = self.client.get('/api/billing/revenuecat/profile/').data
        self.assertFalse(profile['can_restore']); self.assertIsNone(profile['app_user_id']); self.assertIsNone(profile['public_sdk_key'])
        self.assertEqual(self.client.post('/api/billing/revenuecat/sync/', {}).status_code, 403)

    def test_over_limit_company_cannot_purchase_but_can_restore(self):
        from config.models import CompanyConfig
        CompanyConfig.objects.filter(tenant=self.tenant).update(max_users=20)
        for index in range(10): get_user_model().objects.create_user(email=f'over{index}@example.invalid', tenant=self.tenant)
        profile = self.client.get('/api/billing/revenuecat/profile/').data
        self.assertFalse(profile['can_purchase']); self.assertTrue(profile['can_restore']); self.assertTrue(profile['purchase_block_reason'])

    def test_missing_secret_or_test_store_sdk_key_disables_purchases(self):
        for setting in [{'REVENUECAT_SECRET_API_KEY': ''}, {'REVENUECAT_APPLE_PUBLIC_SDK_KEY': 'test_not_production'}]:
            with self.subTest(setting=setting), override_settings(**setting):
                self.assertFalse(self.client.get('/api/billing/revenuecat/profile/').data['store_ready'])
                with self.assertRaises(revenuecat.StoreUnavailable): revenuecat.fetch_customer(self.account.app_user_id)

    def event(self, **changes):
        event = {'id': 'evt-123', 'type': 'RENEWAL', 'app_user_id': str(self.account.app_user_id)}; event.update(changes)
        return {'event': event}

    def post_event(self, body=None, authorization=None):
        return self.client.post('/api/billing/revenuecat/webhook/', body or self.event(), format='json', HTTP_AUTHORIZATION=authorization or settings.REVENUECAT_WEBHOOK_AUTHORIZATION)

    def test_forged_webhook_is_not_processed(self):
        with patch('billing.revenuecat.fetch_customer') as fetch:
            self.assertEqual(self.post_event(authorization='Bearer forged').status_code, 401)
        fetch.assert_not_called(); self.assertFalse(BillingEvent.objects.exists())

    def test_webhook_deduplicates_and_fetches_current_server_state(self):
        with patch('billing.revenuecat.fetch_customer', return_value=self.payload) as fetch:
            self.assertEqual(self.post_event().status_code, 200)
            self.assertEqual(self.post_event().status_code, 200)
        self.assertEqual(fetch.call_count, 1); self.assertEqual(BillingEvent.objects.count(), 1)

    def test_failed_webhook_remains_retryable(self):
        with patch('billing.revenuecat.fetch_customer', side_effect=revenuecat.StoreUnavailable()):
            self.assertEqual(self.post_event().status_code, 503)
        self.assertFalse(BillingEvent.objects.exists())

    def test_test_webhook_is_authenticated_without_granting_access(self):
        self.assertEqual(self.post_event(self.event(type='TEST')).status_code, 200)
        self.assertFalse(CompanySubscription.objects.exists())
        with override_settings(REVENUECAT_WEBHOOK_AUTHORIZATION=''):
            self.assertEqual(self.post_event().status_code, 503)

    def test_transfer_reconciles_both_existing_company_accounts(self):
        other = Tenant.objects.create(name='Other', code='other')
        account = BillingAccount.objects.create(tenant=other)
        with patch('billing.views.sync_subscription') as sync:
            response = self.post_event(self.event(type='TRANSFER', app_user_id=None, transferred_from=[str(self.account.app_user_id)], transferred_to=[str(account.app_user_id)]))
        self.assertEqual(response.status_code, 200); self.assertEqual(sync.call_count, 2)


class RevenueCatV2TransportTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.customer_id = 'b3637c09-de01-40b9-8c7a-339e8be29cbd'
        self.now = int(timezone.now().timestamp()*1000)
        self.expiry = self.now + 86400000
        self.row = {'id': 'subtest', 'customer_id': self.customer_id, 'original_customer_id': self.customer_id,
            'product_id': 'prodtest', 'store': 'app_store', 'environment': 'production',
            'ends_at': self.expiry, 'gives_access': True, 'pending_payment': False,
            'entitlements': {'items': [{'lookup_key': 'company_10', 'state': 'active'}], 'next_page': None}}
        self.app = {'id': 'apptest', 'type': 'app_store', 'app_store': {'bundle_id': 'com.servis.asistani'}}
        self.product = {'id': 'prodtest', 'app_id': 'apptest', 'type': 'subscription', 'store_identifier': next(iter(PRODUCTS))}
        self.calls = []

    def response(self, body, status=200):
        result = Mock(); result.status_code = status; result.json.return_value = body
        return result

    def api(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if '/apps/' in url: return self.response(self.app)
        if '/products/' in url: return self.response(self.product)
        return self.response({'items': [self.row], 'next_page': None})

    def test_read_only_v2_validates_bundle_product_and_customer_before_normalizing(self):
        with patch('billing.revenuecat.requests.get', side_effect=self.api):
            payload = revenuecat.fetch_customer(self.customer_id)
        self.assertEqual(payload['subscriber']['original_app_user_id'], self.customer_id)
        sku = next(iter(PRODUCTS)); self.assertTrue(payload['subscriber']['subscriptions'][sku]['gives_access'])
        for url, kwargs in self.calls:
            self.assertTrue(url.startswith('https://api.revenuecat.com/v2/projects/projtest/'))
            self.assertEqual(kwargs['headers']['Authorization'], 'Bearer ' + settings.REVENUECAT_SECRET_API_KEY)
            self.assertFalse(kwargs['allow_redirects'])

    def test_wrong_bundle_cannot_be_treated_as_an_empty_customer(self):
        self.app['app_store']['bundle_id'] = 'foreign.bundle'
        with patch('billing.revenuecat.requests.get', side_effect=self.api):
            with self.assertRaises(revenuecat.InvalidStoreData): revenuecat.fetch_customer(self.customer_id)
        self.assertEqual(len(self.calls), 1)

    def test_foreign_original_customer_cannot_claim_transferred_receipt(self):
        self.row['original_customer_id'] = 'foreign-company'
        with patch('billing.revenuecat.requests.get', side_effect=self.api):
            with self.assertRaises(revenuecat.InvalidStoreData): revenuecat.fetch_customer(self.customer_id)

    def test_wrong_app_product_is_rejected(self):
        self.product['app_id'] = 'foreign-app'
        with patch('billing.revenuecat.requests.get', side_effect=self.api):
            with self.assertRaises(revenuecat.InvalidStoreData): revenuecat.fetch_customer(self.customer_id)

    def test_pending_payment_does_not_grant_access(self):
        self.row['pending_payment'] = True
        with patch('billing.revenuecat.requests.get', side_effect=self.api):
            payload = revenuecat.fetch_customer(self.customer_id)
        self.assertFalse(payload['subscriber']['subscriptions'][next(iter(PRODUCTS))]['gives_access'])

    def test_paginated_history_does_not_forward_credentials_to_other_domains(self):
        def api(url, **kwargs):
            if '/apps/' in url: return self.response(self.app)
            return self.response({'items': [], 'next_page': 'https://attacker.example/capture'})
        with patch('billing.revenuecat.requests.get', side_effect=api) as get:
            with self.assertRaises(revenuecat.InvalidStoreData): revenuecat.fetch_customer(self.customer_id)
        self.assertEqual(get.call_count, 2)

    def test_missing_customer_is_empty_only_after_correct_app_verification(self):
        def api(url, **kwargs):
            return self.response(self.app) if '/apps/' in url else self.response({}, status=404)
        with patch('billing.revenuecat.requests.get', side_effect=api):
            result = revenuecat.fetch_customer(self.customer_id)
        self.assertEqual(result['subscriber']['entitlements'], {})
