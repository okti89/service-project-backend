import sqlite3
import json
import uuid
from collections import Counter
from contextlib import closing
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.contrib.auth.hashers import identify_hasher
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime, parse_time

from accounts.models import User
from config.models import CompanyConfig
from customers.models import Customer
from products.models import Product
from services.models import (
    DEFAULT_SERVICE_STATUSES,
    Brand,
    DeviceType,
    Model,
    Service,
    ServiceOperations,
    ServiceStatus,
)
from technicians.models import Technician
from tenants.models import Tenant


NAMESPACE = uuid.UUID('a1c5700b-cac7-42d5-9b4e-d6b2746962b6')
DEVICE_NAMES = {
    'combi': 'Kombi',
    'air_conditioner': 'Klima',
    'washing_machine': 'Çamaşır Makinesi',
    'dishwasher': 'Bulaşık Makinesi',
    'refrigerator': 'Buzdolabı',
    'freezer': 'Derin Dondurucu',
    'water_purification': 'Su Arıtma',
}
STATUS_CODES = {
    'received': 'new',
    'in_progress': 'in_progress',
    'completed': 'completed',
    'canceled': 'cancelled',
    'cancelled': 'cancelled',
    'postponed': 'postponed',
}
REQUIRED_COLUMNS = {
    'users': {'id', 'email', 'password', 'first_name', 'last_name', 'is_staff', 'is_active'},
    'services_service': {'id', 'full_name', 'receipt_number', 'status', 'created_at'},
    'services_process': {'id', 'service_id', 'name', 'price', 'quantity'},
    'services_sparepart': {'id', 'name', 'price', 'stock'},
}
JSON_FORMAT = 'erkmen-legacy-sqlite-v1'


def stable_id(tenant_code, kind, source_id):
    return uuid.uuid5(NAMESPACE, f'{tenant_code}:{kind}:{source_id}')


def clean(value, max_length=None):
    text = str(value or '').strip()
    return text[:max_length] if max_length else text


def money(value):
    try:
        amount = Decimal(str(value or '0')).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError) as exc:
        raise CommandError(f'Gecersiz parasal deger: {value}') from exc
    if abs(amount) > Decimal('99999999.99'):
        raise CommandError(f'Parasal deger alan sinirini asiyor: {value}')
    return amount


def aware(value):
    parsed = parse_datetime(str(value or ''))
    if not parsed:
        return None
    return timezone.make_aware(parsed, timezone.get_current_timezone()) if timezone.is_naive(parsed) else parsed


class Command(BaseCommand):
    help = 'Erkmen eski Django SQLite verisini tenant altina aktarir; varsayilan mod dry-run.'

    def add_arguments(self, parser):
        parser.add_argument('source', help='PythonAnywhere kaynakli db.sqlite3 veya tum tablolari iceren JSON')
        parser.add_argument('--tenant-code', default='erkmen-teknik')
        parser.add_argument('--expected-tenant-id', help='Var olan tenant UUID dogrulamasi')
        parser.add_argument(
            '--email-alias', action='append', default=[], metavar='ESKI=YENI',
            help='Baska tenantta kullanilan eski e-postayi yeni e-postaya esler',
        )
        parser.add_argument(
            '--skip-user', action='append', default=[], metavar='EPOSTA',
            help='Eski kullaniciyi aktarim disinda birakir',
        )
        parser.add_argument('--commit', action='store_true', help='Prova yerine verileri kaydeder')

    def handle(self, *args, **options):
        source = Path(options['source']).expanduser().resolve()
        if not source.is_file():
            raise CommandError(f'Kaynak dosya bulunamadi: {source}')
        target = settings.DATABASES['default'].get('NAME')
        if target and Path(str(target)).exists() and source.samefile(target):
            raise CommandError('Kaynak ve hedef veritabani ayni dosya olamaz.')

        self.tenant_code = clean(options['tenant_code'], 64).lower()
        self.email_aliases = {}
        self.skipped_users = {value.strip().lower() for value in options['skip_user']}
        for mapping in options['email_alias']:
            if '=' not in mapping:
                raise CommandError('--email-alias ESKI=YENI biciminde olmali.')
            original, replacement = (part.strip().lower() for part in mapping.split('=', 1))
            try:
                validate_email(original)
                validate_email(replacement)
            except ValidationError as exc:
                raise CommandError('E-posta eslestirmesinde gecersiz adres var.') from exc
            if original in self.email_aliases or replacement in self.email_aliases.values():
                raise CommandError('Tekrarlanan e-posta eslestirmesi var.')
            self.email_aliases[original] = replacement
        self.stats = Counter()
        if source.suffix.lower() == '.json':
            self.rows = self._read_json(source)
        else:
            try:
                with closing(sqlite3.connect(f'{source.as_uri()}?mode=ro', uri=True)) as connection:
                    connection.row_factory = sqlite3.Row
                    self._validate_source(connection)
                    self.rows = {
                        table: [dict(row) for row in connection.execute(f'SELECT * FROM {table}')]
                        for table in REQUIRED_COLUMNS
                    }
            except sqlite3.DatabaseError as exc:
                raise CommandError(f'SQLite yedegi okunamadi: {exc}') from exc

        with transaction.atomic():
            self._resolve_tenant(options.get('expected_tenant_id'))
            self._import_users()
            self._import_products()
            self._import_services()
            self._import_operations()
            if not options['commit']:
                transaction.set_rollback(True)

        mode = 'KAYDEDILDI' if options['commit'] else 'DRY-RUN, VERITABANI DEGISMEDI'
        self.stdout.write(self.style.SUCCESS(f'{mode}: {self.tenant_code}'))
        for name, count in sorted(self.stats.items()):
            self.stdout.write(f'  {name}: {count}')

    def _validate_source(self, connection):
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, columns in REQUIRED_COLUMNS.items():
            if table not in tables:
                raise CommandError(f'Eski veritabaninda tablo eksik: {table}')
            available = {row[1] for row in connection.execute(f'PRAGMA table_info({table})')}
            missing = columns - available
            if missing:
                raise CommandError(f'{table} tablosunda alan eksik: {", ".join(sorted(missing))}')

    def _read_json(self, source):
        try:
            with source.open('r', encoding='utf-8') as stream:
                payload = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CommandError(f'JSON okunamadi: {exc}') from exc
        if not isinstance(payload, dict) or payload.get('format') != JSON_FORMAT:
            raise CommandError('JSON bicimi beklenen Erkmen SQLite disa aktarimi degil.')
        tables = payload.get('tables')
        if not isinstance(tables, dict):
            raise CommandError('JSON tablo listesi eksik.')
        rows = {}
        for table, required in REQUIRED_COLUMNS.items():
            entry = tables.get(table)
            if not isinstance(entry, dict):
                raise CommandError(f'JSON tablosu eksik: {table}')
            columns = entry.get('columns')
            items = entry.get('rows')
            if not isinstance(columns, list) or not isinstance(items, list):
                raise CommandError(f'JSON tablosu gecersiz: {table}')
            missing = required - set(columns)
            if missing:
                raise CommandError(f'{table} tablosunda alan eksik: {", ".join(sorted(missing))}')
            if any(not isinstance(item, dict) or not required.issubset(item) for item in items):
                raise CommandError(f'{table} tablosunda eksik veya gecersiz satir var.')
            rows[table] = items
        return rows

    def _resolve_tenant(self, expected_id):
        self.tenant = Tenant.objects.filter(code=self.tenant_code).first()
        if self.tenant and expected_id and str(self.tenant.pk) != expected_id:
            raise CommandError('Hedef tenant UUID beklenen degerle uyusmuyor.')
        if not self.tenant:
            if expected_id:
                raise CommandError('Beklenen hedef tenant bulunamadi.')
            self.tenant = Tenant.objects.create(
                code=self.tenant_code, name='Erkmen Teknik', app_name='Erkmen Teknik',
            )
            self.stats['tenants_created'] += 1
        CompanyConfig.objects.get_or_create(
            tenant=self.tenant, defaults={'name': 'Erkmen Teknik'},
        )

    def _import_users(self):
        for row in self.rows['users']:
            original_email = clean(row.get('email'), 254).lower()
            if original_email in self.skipped_users:
                self.stats['users_skipped'] += 1
                continue
            email = self.email_aliases.get(original_email, original_email)
            if not email:
                raise CommandError('Eski kullanicinin e-postasi bos. Aktarim durduruldu.')
            existing = User.objects.filter(email__iexact=email).first()
            if existing:
                if existing.tenant_id != self.tenant.id:
                    raise CommandError(f'Kullanici e-postasi baska tenantta: {email}')
                self.stats['users_preserved'] += 1
                continue

            old_hash = clean(row.get('password'))
            try:
                identify_hasher(old_hash)
            except ValueError:
                old_hash = ''
                self.stats['unsupported_password_hashes'] += 1
            is_admin = bool(row.get('is_staff') or row.get('is_superuser'))
            user = User(
                id=stable_id(self.tenant_code, 'user', row['id']),
                tenant=self.tenant,
                email=email,
                first_name=clean(row.get('first_name'), 150),
                last_name=clean(row.get('last_name'), 150),
                password=old_hash,
                user_type='admin' if is_admin else 'technician',
                approval_status='approved',
                is_active=bool(row.get('is_active')) and bool(old_hash),
                is_staff=is_admin,
                is_superuser=False,
            )
            if not old_hash:
                user.set_unusable_password()
            user.save()
            self.stats['users_created'] += 1
            if not is_admin:
                Technician.objects.get_or_create(user=user, defaults={'tenant': self.tenant})
                self.stats['technicians_created'] += 1

    def _import_products(self):
        self.products = {}
        for row in self.rows['services_sparepart']:
            source_id = row['id']
            code = f'ERK-{source_id}'
            product = Product.objects.filter(tenant=self.tenant, code=code).first()
            if not product:
                product = Product.objects.create(
                    id=stable_id(self.tenant_code, 'sparepart', source_id),
                    tenant=self.tenant,
                    code=code,
                    name=clean(row.get('name'), 200) or f'Eski parca {source_id}',
                    price=money(row.get('price')),
                    stock_quantity=max(0, int(row.get('stock') or 0)),
                )
                self.stats['products_created'] += 1
            self.products[source_id] = product

    def _named(self, model, name, **extra):
        name = clean(name, 50)
        if not name:
            return None
        query = model.objects.filter(tenant=self.tenant, name__iexact=name, **extra)
        return query.first() or model.objects.create(tenant=self.tenant, name=name, **extra)

    def _scheduled_at(self, row):
        date_value = parse_date(str(row.get('appointment_date') or ''))
        if date_value:
            time_value = parse_time(str(row.get('appointment_time') or '')) or time(12, 0)
            return timezone.make_aware(datetime.combine(date_value, time_value))
        return aware(row.get('created_at')) or timezone.now()

    def _import_services(self):
        self.services = {}
        for row in self.rows['services_service']:
            source_id = uuid.UUID(str(row['id']))
            existing = Service.objects.filter(pk=source_id).first()
            if existing:
                if existing.tenant_id != self.tenant.id:
                    raise CommandError(f'Servis UUID baska tenantta: {source_id}')
                self.services[str(source_id)] = existing
                self.stats['services_preserved'] += 1
                continue

            receipt = clean(row.get('receipt_number'), 20)
            if receipt and Service.objects.filter(receipt_number=receipt).exists():
                raise CommandError(f'Makbuz numarasi zaten kullaniliyor: {receipt}')
            code = STATUS_CODES.get(clean(row.get('status')).lower())
            if not code:
                raise CommandError(f'Bilinmeyen eski servis durumu: {row.get("status")}')
            status = ServiceStatus.objects.filter(tenant=self.tenant, code=code).first()
            if not status:
                _, name, color, order, terminal = next(
                    item for item in DEFAULT_SERVICE_STATUSES if item[0] == code
                )
                status = ServiceStatus.objects.create(
                    tenant=self.tenant, code=code, name=name, color=color,
                    sort_order=order, is_terminal=terminal, is_default=code == 'new',
                )

            full_name = clean(row.get('full_name'), 200) or 'Isimsiz Musteri'
            phone = clean(row.get('phone_number'), 20)
            address = clean(row.get('address'))
            customer_id = stable_id(self.tenant_code, 'customer', f'{full_name.casefold()}:{phone}')
            customer = Customer.objects.filter(pk=customer_id).first()
            if not customer:
                customer = Customer.objects.create(
                    id=customer_id, tenant=self.tenant, full_name=full_name,
                    phone_number=phone, address=address,
                )
                self.stats['customers_created'] += 1
            elif customer.tenant_id != self.tenant.id:
                raise CommandError(f'Musteri UUID baska tenantta: {customer_id}')

            brand = self._named(Brand, row.get('brand'))
            model = self._named(Model, row.get('model'), brand=brand) if brand else None
            device_code = clean(row.get('device_type'))
            device_type = self._named(DeviceType, DEVICE_NAMES.get(device_code, device_code))
            service = Service.objects.create(
                id=source_id, tenant=self.tenant, customer=customer,
                customer_full_name=full_name, customer_phone=phone,
                customer_address=address, fault_description=clean(row.get('complaint')),
                device_type=device_type, device_brand=brand, device_model=model,
                status=status, receipt_number=receipt or None,
                scheduled_date=self._scheduled_at(row),
                legacy_data={'source': 'erkmen-sqlite', 'record': row},
            )
            created_at = aware(row.get('created_at'))
            updated_at = aware(row.get('updated_at'))
            if created_at or updated_at:
                Service.objects.filter(pk=source_id).update(
                    created_at=created_at or service.created_at,
                    updated_at=updated_at or service.updated_at,
                )
            self.services[str(source_id)] = service
            self.stats['services_created'] += 1

    def _import_operations(self):
        for row in self.rows['services_process']:
            try:
                source_service_id = str(uuid.UUID(str(row['service_id'])))
            except ValueError as exc:
                raise CommandError(f'Gecersiz islem servis UUID: {row["service_id"]}') from exc
            service = self.services.get(source_service_id)
            if not service:
                raise CommandError(f'Islem icin servis bulunamadi: {row["service_id"]}')
            operation_id = stable_id(self.tenant_code, 'process', row['id'])
            existing = ServiceOperations.objects.filter(pk=operation_id).first()
            if existing:
                if existing.service_id != service.id:
                    raise CommandError(f'Islem UUID baska serviste: {operation_id}')
                self.stats['operations_preserved'] += 1
                continue
            spare_part_id = row.get('spare_part_id')
            if spare_part_id and spare_part_id not in self.products:
                self.stats['missing_part_references'] += 1
            ServiceOperations.objects.bulk_create([ServiceOperations(
                id=operation_id, tenant=self.tenant, service=service,
                product=self.products.get(spare_part_id),
                name=clean(row.get('name'), 255) or 'Eski Islem',
                quantity=max(1, int(row.get('quantity') or 1)),
                unit_price=money(row.get('price')),
                legacy_data={'source': 'erkmen-sqlite', 'record': row},
            )])
            self.stats['operations_created'] += 1
