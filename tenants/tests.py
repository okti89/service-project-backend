from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
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

    def test_trial_membership_defaults_to_five_days(self):
        tenant = Tenant.objects.create(name='Manual Trial Tenant', code='manual-trial-tenant')
        tenant.memberships.all().delete()
        start = timezone.localdate()

        membership = TenantMembership.objects.create(
            tenant=tenant,
            plan=TenantMembership.Plan.TRIAL,
            premium_started_at=start,
        )

        self.assertEqual(membership.renewal_date, start + timedelta(days=5))


class TenantMembershipAdminTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Editable Tenant', code='editable-tenant')
        self.membership = self.tenant.memberships.get()
        self.admin_user = User.objects.create_superuser('membership-admin@example.com', 'pass123')
        self.client.force_login(self.admin_user)
        self.url = reverse('admin:tenants_tenantmembership_change', args=[self.membership.pk])

    def test_admin_can_edit_membership_plan_and_dates(self):
        start = timezone.localdate()
        end = start + timedelta(days=45)

        response = self.client.post(self.url, {
            'tenant': str(self.tenant.pk),
            'plan': TenantMembership.Plan.PREMIUM,
            'premium_started_at': start.isoformat(),
            'renewal_date': end.isoformat(),
            '_save': 'Kaydet',
        })

        self.assertEqual(response.status_code, 302)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.plan, TenantMembership.Plan.PREMIUM)
        self.assertEqual(self.membership.renewal_date, end)
        self.assertEqual(self.membership.period_number, 1)

    def test_admin_starts_trial_when_trial_plan_is_selected(self):
        start = timezone.localdate()
        self.membership.delete()

        response = self.client.post(reverse('admin:tenants_tenantmembership_add'), {
            'tenant': str(self.tenant.pk),
            'plan': TenantMembership.Plan.TRIAL,
            'premium_started_at': start.isoformat(),
            'renewal_date': '',
            '_save': 'Kaydet',
        })

        self.assertEqual(response.status_code, 302)
        membership = self.tenant.memberships.get()
        self.assertEqual(membership.plan, TenantMembership.Plan.TRIAL)
        self.assertEqual(membership.renewal_date, start + timedelta(days=5))

    def test_admin_rejects_end_before_start(self):
        start = timezone.localdate()
        response = self.client.post(self.url, {
            'tenant': str(self.tenant.pk),
            'plan': TenantMembership.Plan.TRIAL,
            'premium_started_at': start.isoformat(),
            'renewal_date': (start - timedelta(days=1)).isoformat(),
            '_save': 'Kaydet',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Yenileme tarihi başlangıç tarihinden sonra olmalıdır.')
        self.membership.refresh_from_db()
        self.assertGreater(self.membership.renewal_date, start)

    def test_existing_membership_tenant_cannot_be_changed(self):
        other_tenant = Tenant.objects.create(name='Other Tenant', code='other-tenant')
        response = self.client.post(self.url, {
            'tenant': str(other_tenant.pk),
            'plan': self.membership.plan,
            'premium_started_at': self.membership.premium_started_at.isoformat(),
            'renewal_date': self.membership.renewal_date.isoformat(),
            '_save': 'Kaydet',
        })

        self.assertEqual(response.status_code, 302)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.tenant, self.tenant)
