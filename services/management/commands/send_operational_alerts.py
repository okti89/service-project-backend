from datetime import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

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
        parser.add_argument(
            '--not-before',
            help='Bu yerel saatten once bildirim gondermeden cikar (HH:MM).',
        )

    def handle(self, *args, **options):
        not_before = options.get('not_before')
        if not_before:
            try:
                earliest_time = time.fromisoformat(not_before)
            except ValueError as exc:
                raise CommandError('--not-before HH:MM formatinda olmali.') from exc
            if timezone.localtime().time() < earliest_time:
                self.stdout.write(f'Bildirim zamani henuz gelmedi: {not_before}')
                return

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