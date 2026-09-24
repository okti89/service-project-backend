from django.core.management.base import CommandError

from .import_erkmen_sqlite import Command as LegacyImportCommand


class Command(LegacyImportCommand):
    help = 'Erkmen tum-tablo JSON yedeginden tenant altina aktarir; varsayilan mod dry-run.'

    def handle(self, *args, **options):
        if not str(options['source']).lower().endswith('.json'):
            raise CommandError('Bu komut yalnizca .json dosyasi kabul eder.')
        return super().handle(*args, **options)
