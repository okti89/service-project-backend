import sqlite3
import json
import uuid
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from accounts.models import User
from customers.models import Customer
from products.models import Product
from services.models import Service, ServiceOperations
from services.serializers import ServiceSerializer
from tenants.models import Tenant
from tools.export_legacy_sqlite_json import export
from tools.prepare_erkmen_import_json import prepare


class ErkmenSqliteImportTests(TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.source = Path(self.temp_dir.name) / 'db.sqlite3'
        self.service_id = str(uuid.uuid4())
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.executescript('''
                CREATE TABLE users (
                    id TEXT, email TEXT, password TEXT, first_name TEXT,
                    last_name TEXT, is_staff INTEGER, is_superuser INTEGER, is_active INTEGER
                );
                CREATE TABLE services_service (
                    id TEXT, full_name TEXT, receipt_number TEXT, status TEXT,
                    created_at TEXT, updated_at TEXT, appointment_date TEXT,
                    appointment_time TEXT, phone_number TEXT, address TEXT,
                    complaint TEXT, device_type TEXT, brand TEXT, model TEXT,
                    custom_note TEXT, technician_notes TEXT, garanty TEXT
                );
                CREATE TABLE services_process (
                    id INTEGER, service_id TEXT, name TEXT, price TEXT,
                    quantity INTEGER, spare_part_id INTEGER
                );
                CREATE TABLE services_sparepart (
                    id INTEGER, name TEXT, price TEXT, stock INTEGER
                );
            ''')
            connection.execute(
                'INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (str(uuid.uuid4()), 'erkmen@example.com', make_password('StrongPassword123!'),
                 'Erkmen', 'Yonetici', 1, 1, 1),
            )
            connection.execute(
                'INSERT INTO services_service VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (self.service_id, 'Ayse Yilmaz', 'ERK-100', 'completed',
                 '2025-12-01 10:00:00', '2025-12-02 11:00:00', '2025-12-02',
                 '09:30:00', '05551234567', 'Istanbul', 'Isitmiyor', 'combi',
                 'Arcelik', 'Model X', 'Ozel not', 'Teknisyen notu', '2 yil'),
            )
            connection.execute(
                'INSERT INTO services_sparepart VALUES (1, ?, ?, ?)',
                ('Valf', '250.00', 5),
            )
            connection.execute(
                'INSERT INTO services_process VALUES (1, ?, ?, ?, ?, ?)',
                (uuid.UUID(self.service_id).hex, 'Valf degisimi', '300.00', 2, 1),
            )

    def test_dry_run_does_not_write(self):
        call_command('import_erkmen_sqlite', str(self.source), verbosity=0)
        self.assertFalse(Tenant.objects.filter(code='erkmen-teknik').exists())
        self.assertFalse(Service.objects.filter(pk=self.service_id).exists())

    def test_json_export_and_import_preserve_unicode(self):
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.execute(
                'UPDATE services_service SET full_name = ? WHERE id = ?',
                ('Ayşe Yılmaz', self.service_id),
            )
        snapshot = Path(self.temp_dir.name) / 'erkmen.json'
        counts = export(self.source, snapshot)
        self.assertEqual(counts['services_service'], 1)
        payload = json.loads(snapshot.read_text(encoding='utf-8'))
        self.assertEqual(payload['tables']['services_service']['rows'][0]['full_name'], 'Ayşe Yılmaz')

        call_command('import_erkmen_json', str(snapshot), verbosity=0)
        self.assertFalse(Tenant.objects.filter(code='erkmen-teknik').exists())
        call_command('import_erkmen_json', str(snapshot), '--commit', verbosity=0)
        self.assertEqual(Service.objects.get(pk=self.service_id).customer_full_name, 'Ayşe Yılmaz')

    def test_prepared_json_excludes_tokens_and_skipped_user(self):
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.execute('CREATE TABLE authtoken_token (key TEXT)')
            connection.execute('INSERT INTO authtoken_token VALUES (?)', ('secret-token',))
            connection.execute(
                'INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (str(uuid.uuid4()), 'skip@example.com', make_password('SkippedPassword123!'),
                 'Skip', 'User', 1, 1, 1),
            )
        full = Path(self.temp_dir.name) / 'full.json'
        prepared = Path(self.temp_dir.name) / 'prepared.json'
        export(self.source, full)
        counts = prepare(full, prepared, ['skip@example.com'])
        self.assertEqual(counts['users'], 1)
        payload = json.loads(prepared.read_text(encoding='utf-8'))
        self.assertEqual(len(payload['tables']), 4)
        self.assertNotIn('authtoken_token', payload['tables'])
        self.assertNotIn('secret-token', prepared.read_text(encoding='utf-8'))
        self.assertEqual(payload['excluded_users'], ['skip@example.com'])
        call_command('import_erkmen_json', str(prepared), '--commit', verbosity=0)
        self.assertEqual(User.objects.filter(tenant__code='erkmen-teknik').count(), 1)

    def test_missing_json_reports_source_path(self):
        missing = Path(self.temp_dir.name) / 'missing.json'
        with self.assertRaisesMessage(CommandError, f'Kaynak dosya bulunamadi: {missing}'):
            call_command('import_erkmen_json', str(missing), verbosity=0)

    def test_commit_maps_data_and_is_idempotent(self):
        call_command('import_erkmen_sqlite', str(self.source), '--commit', verbosity=0)
        tenant = Tenant.objects.get(code='erkmen-teknik')
        service = Service.objects.get(pk=self.service_id)
        self.assertEqual(service.tenant, tenant)
        self.assertEqual(service.service_status, 'completed')
        self.assertEqual(service.customer_full_name, 'Ayse Yilmaz')
        self.assertEqual(service.device_type.name, 'Kombi')
        self.assertEqual(service.legacy_data['record']['custom_note'], 'Ozel not')
        self.assertEqual(service.legacy_data['record']['garanty'], '2 yil')
        details = ServiceSerializer(service).data
        self.assertEqual(details['historical_warranty'], '2 yil')
        self.assertEqual(details['historical_technician_notes'], 'Teknisyen notu')
        self.assertEqual(details['historical_custom_note'], 'Ozel not')
        self.assertNotIn('legacy_data', details)
        self.assertEqual(Customer.objects.filter(tenant=tenant).count(), 1)
        self.assertEqual(Product.objects.get(tenant=tenant).stock_quantity, 5)
        self.assertEqual(ServiceOperations.objects.get(service=service).unit_price, 300)
        user = User.objects.get(tenant=tenant)
        self.assertTrue(user.check_password('StrongPassword123!'))
        self.assertFalse(user.is_superuser)

        call_command('import_erkmen_sqlite', str(self.source), '--commit', verbosity=0)
        self.assertEqual(Service.objects.filter(tenant=tenant).count(), 1)
        self.assertEqual(ServiceOperations.objects.filter(service=service).count(), 1)

    def test_skipped_user_and_missing_part_reference(self):
        other_tenant = Tenant.objects.create(code='other', name='Other')
        existing = User.objects.create_user(
            email='shared@example.com', password='ExistingPassword123!', tenant=other_tenant,
        )
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.execute(
                'INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (str(uuid.uuid4()), existing.email, make_password('LegacyPassword123!'),
                 'Existing', 'Admin', 1, 1, 1),
            )
            connection.execute(
                'INSERT INTO services_process VALUES (2, ?, ?, ?, ?, ?)',
                (self.service_id, 'Eski parca', '25.00', 1, 999),
            )

        call_command(
            'import_erkmen_sqlite', str(self.source), '--commit',
            '--skip-user', existing.email, verbosity=0,
        )
        existing.refresh_from_db()
        self.assertEqual(existing.tenant, other_tenant)
        tenant = Tenant.objects.get(code='erkmen-teknik')
        self.assertEqual(User.objects.filter(tenant=tenant).count(), 1)
        orphan_operation = ServiceOperations.objects.get(name='Eski parca')
        self.assertIsNone(orphan_operation.product)
        self.assertEqual(orphan_operation.legacy_data['record']['spare_part_id'], 999)
