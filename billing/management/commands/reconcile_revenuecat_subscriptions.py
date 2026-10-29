from django.core.management.base import BaseCommand, CommandError
from billing.models import BillingAccount
from billing.services import sync_subscription
from billing.revenuecat import InvalidStoreData, StoreUnavailable

class Command(BaseCommand):
    help = 'Refresh company subscriptions after missed RevenueCat webhooks (schedule hourly).'
    def handle(self, *args, **options):
        failed = 0
        for account in BillingAccount.objects.select_related('tenant').iterator():
            try:
                sync_subscription(account.tenant)
            except (InvalidStoreData, StoreUnavailable):
                failed += 1
        if failed:
            raise CommandError(f'{failed} subscription refreshes failed; retry required.')
        self.stdout.write('RevenueCat subscription reconciliation completed.')
