from django.core.management.base import BaseCommand

from services.operational_alerts import send_operational_alerts


class Command(BaseCommand):
    help = 'Atanmamis, geciken ve tahsilati eksik servisler icin operasyon uyarilari gonderir.'

    def handle(self, *args, **options):
        result = send_operational_alerts()
        self.stdout.write(self.style.SUCCESS(
            f"Operasyon uyarilari tamamlandi. Tarih: {result['date']}, "
            f"atanmamis: {result['unassigned']}, geciken: {result['overdue']}, "
            f"tahsilat: {result['receivable']}"
        ))
