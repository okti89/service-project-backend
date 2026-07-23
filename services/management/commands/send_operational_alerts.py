from django.core.management.base import BaseCommand

from services.operational_alerts import send_operational_alerts


class Command(BaseCommand):
    help = 'Atanmamis, geciken ve tahsilati eksik servisler icin operasyon uyarilari gonderir.'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            '--only-status-reminders',
            action='store_true',
            help='Yalnizca teknisyenlere servis durumu guncelleme hatirlatmasi gonderir.',
        )
        group.add_argument(
            '--exclude-status-reminders',
            action='store_true',
            help='Teknisyen servis durum hatirlatmalarini atlayarak diger operasyon uyarilarini gonderir.',
        )

    def handle(self, *args, **options):
        only_status_reminders = options['only_status_reminders']
        result = send_operational_alerts(
            include_unassigned=not only_status_reminders,
            include_overdue_manager_alerts=not only_status_reminders,
            include_technician_status_reminders=not options['exclude_status_reminders'],
            include_receivable=not only_status_reminders,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Operasyon uyarilari tamamlandi. Tarih: {result['date']}, "
            f"atanmamis: {result['unassigned']}, geciken: {result['overdue']}, "
            f"tahsilat: {result['receivable']}"
        ))