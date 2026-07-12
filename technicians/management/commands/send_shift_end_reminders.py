from django.core.management.base import BaseCommand

from technicians.shift_reminders import send_shift_end_reminders


class Command(BaseCommand):
    help = 'Mesai bitis saati gecmis, acik mesaisi olan teknisyenlere hatirlatma gonderir.'

    def add_arguments(self, parser):
        parser.add_argument('--grace-minutes', type=int, default=15)
        parser.add_argument('--force', action='store_true', help='Ayni gunun mevcut hatirlatmalarini yeniden gonder.')

    def handle(self, *args, **options):
        result = send_shift_end_reminders(
            grace_minutes=options['grace_minutes'],
            force=options['force'],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Mesai bitis hatirlatmasi tamamlandi. Tarih: {result['date']}, "
            f"gonderilen: {result['sent']}, atlanan: {result['skipped']}"
        ))
