from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from technicians.shift_reminders import send_shift_start_reminders


class Command(BaseCommand):
    help = 'Mesai baslangici gecmis, ancak mesai kaydi olmayan teknisyenlere hatirlatma gonderir.'

    def add_arguments(self, parser):
        parser.add_argument('--grace-minutes', type=int, default=10)
        parser.add_argument('--at', help='Test icin zaman (YYYY-MM-DDTHH:MM:SS).')
        parser.add_argument('--force', action='store_true', help='Ayni gunun mevcut hatirlatmalarini yeniden gonder.')

    def handle(self, *args, **options):
        if options['grace_minutes'] < 0:
            raise CommandError('--grace-minutes sifirdan kucuk olamaz.')

        now = None
        if options['at']:
            try:
                now = datetime.fromisoformat(options['at'])
            except ValueError as exc:
                raise CommandError('--at ISO tarih-saat formatinda olmali.') from exc
            if timezone.is_naive(now):
                now = timezone.make_aware(now, timezone.get_current_timezone())

        result = send_shift_start_reminders(
            now=now,
            grace_minutes=options['grace_minutes'],
            force=options['force'],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Mesai baslangic hatirlatmasi tamamlandi. Tarih: {result['date']}, "
            f"gonderilen: {result['sent']}, atlanan: {result['skipped']}"
        ))
