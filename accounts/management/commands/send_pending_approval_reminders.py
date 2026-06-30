from django.core.management.base import BaseCommand

from accounts.reminder_services import send_pending_approval_reminders


class Command(BaseCommand):
    help = 'Onay bekleyen kullanicilar icin yoneticilere bildirim ve mail hatirlatmasi gonderir.'

    def add_arguments(self, parser):
        parser.add_argument('--hours', type=int, default=24, help='Ayni kullaniciya hatirlatma araligi (saat)')
        parser.add_argument('--user-id', type=str, default=None, help='Sadece tek kullanici icin tetikle')

    def handle(self, *args, **options):
        sent_count = send_pending_approval_reminders(
            interval_hours=options['hours'],
            only_user_id=options['user_id'],
        )
        self.stdout.write(self.style.SUCCESS(f'Hatirlatma gonderilen bekleyen kullanici sayisi: {sent_count}'))

