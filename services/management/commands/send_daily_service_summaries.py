from datetime import date

from django.core.management.base import BaseCommand, CommandError

from services.daily_summary import send_daily_service_summaries


class Command(BaseCommand):
    help = 'Aktif kullanicilara gunluk servis ozet bildirimlerini gonderir.'

    def add_arguments(self, parser):
        parser.add_argument('--date', help='Ozet tarihi (YYYY-MM-DD). Varsayilan: bugun.')
        parser.add_argument('--force', action='store_true', help='Ayni gunun mevcut ozetlerini yeniden gonder.')

    def handle(self, *args, **options):
        summary_date = None
        if options['date']:
            try:
                summary_date = date.fromisoformat(options['date'])
            except ValueError as exc:
                raise CommandError('--date YYYY-MM-DD formatinda olmali.') from exc

        result = send_daily_service_summaries(
            summary_date=summary_date,
            force=options['force'],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Gunluk servis ozeti tamamlandi. Tarih: {result['date']}, "
            f"gonderilen: {result['sent']}, atlanan: {result['skipped']}"
        ))
