from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .models import Tenant, TenantMembership


class TenantSubscriptionTests(TestCase):
    def test_new_tenant_starts_one_five_day_trial(self):
        tenant = Tenant.objects.create(name='Trial Tenant', code='trial-tenant')

        membership = tenant.memberships.get()
        self.assertEqual(membership.plan, TenantMembership.Plan.TRIAL)
        self.assertEqual(membership.premium_started_at, timezone.localdate())
        self.assertEqual(membership.renewal_date, timezone.localdate() + timedelta(days=5))
        self.assertTrue(tenant.subscription_info()['is_active'])

    def test_ended_membership_blocks_subscription(self):
        tenant = Tenant.objects.create(name='Expired Tenant', code='expired-tenant')
        membership = tenant.memberships.get()
        membership.renewal_date = timezone.localdate()
        membership.save(update_fields=['renewal_date'])

        subscription = tenant.subscription_info()
        self.assertFalse(subscription['is_active'])
        self.assertEqual(subscription['status'], 'expired')

    def test_trial_can_only_start_once(self):
        tenant = Tenant.objects.create(name='One Trial Tenant', code='one-trial-tenant')

        self.assertIsNone(tenant.start_trial())
        self.assertEqual(tenant.memberships.count(), 1)