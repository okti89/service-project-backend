from django.core.management.base import BaseCommand, CommandError
from billing.models import AppleSubscription
from billing.services import verify_purchase
from billing.apple import InvalidPurchase, StoreUnavailable

class Command(BaseCommand):
    help = 'Refresh Apple subscriptions after webhook delivery failures (schedule hourly).'
    def handle(self, *args, **options):
        failed = 0
        for row in AppleSubscription.objects.select_related('account__tenant').iterator():
            try:
                verify_purchase(row.account.tenant, row.transaction_id)
            except (InvalidPurchase, StoreUnavailable):
                failed += 1
        if failed:
            raise CommandError(f'{failed} Apple subscription refreshes failed; retry required.')
        self.stdout.write('Apple subscription reconciliation completed.')
