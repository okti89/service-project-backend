import hashlib
import json
import re
import unicodedata
import uuid
from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.contrib.auth.hashers import identify_hasher
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounting.models import Account, Transaction, TransactionCategory
from accounts.models import User
from config.models import CompanyConfig
from customers.models import Customer
from customers.serializers import CustomerSerializer
from products.models import Product, ProductCategory
from services.models import (
    Brand,
    DeviceType,
    PaymentMethod,
    Service,
    ServiceOperations,
    ServicePayment,
    ServiceStatus,
)
from technicians.models import Technician
from tenants.models import Tenant


LEGACY_NAMESPACE = uuid.UUID('bfcc6ddd-4928-4a56-a253-f712d104fdba')
SUPPORTED_TABLES = {
    'cihaztipleri',
    'kasa',
    'malzeme_arac_kullanilan',
    'malzeme_listesi',
    'markalar',
    'servis_hizmetlerimiz',
    'servis_musteriler',
    'servis_musteriler2',
    'servis_randevular',
    'yonetim',
}


def clean_text(value, max_length=None):
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    return text[:max_length] if max_length else text


def normalized_key(value):
    text = clean_text(value).casefold()
    text = ''.join(
        char for char in unicodedata.normalize('NFKD', text)
        if not unicodedata.combining(char)
    )
    return re.sub(r'[^a-z0-9]+', '', text)


def legacy_uuid(tenant_code, kind, source_key):
    return uuid.uuid5(LEGACY_NAMESPACE, f'{tenant_code}:{kind}:{source_key}')


def parse_decimal(value):
    raw = clean_text(value).replace('₺', '').replace('TL', '').replace(' ', '')
    if not raw:
        return Decimal('0.00')

    if ',' in raw and '.' in raw:
        if raw.rfind(',') > raw.rfind('.'):
            raw = raw.replace('.', '').replace(',', '.')
        else:
            raw = raw.replace(',', '')
    elif ',' in raw:
        raw = raw.replace(',', '.')

    try:
        return Decimal(raw).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return Decimal('0.00')


def parse_positive_int(value, default=1):
    try:
        parsed = int(Decimal(clean_text(value) or str(default)))
    except (InvalidOperation, ValueError):
        return default
    return max(parsed, default)


def parse_date(value):
    raw = clean_text(value)
    if not raw or raw.startswith('0000-00-00'):
        return None
    for date_format in ('%Y-%m-%d', '%d.%m.%Y', '%Y-%m-%d %H:%M:%S'):
        try:
            parsed = datetime.strptime(raw, date_format).date()
            return parsed if parsed.year >= 2019 else None
        except ValueError:
            continue
    return None


def parse_time(value):
    raw = clean_text(value)
    if not raw:
        return time(12, 0)
    for time_format in ('%H:%M:%S', '%H:%M'):
        try:
            return datetime.strptime(raw, time_format).time()
        except ValueError:
            continue
    return time(12, 0)


def aware_datetime(date_value, time_value=None):
    parsed_date = parse_date(date_value)
    if not parsed_date:
        return None
    naive = datetime.combine(parsed_date, parse_time(time_value))
    return timezone.make_aware(naive, timezone.get_current_timezone())


def split_name(value):
    parts = clean_text(value, 300).split(' ', 1)
    return (parts[0][:150], parts[1][:150] if len(parts) > 1 else '')


def status_code(value, has_completion=False):
    key = normalized_key(value)
    if 'ptal' in key or 'cancel' in key:
        return 'cancelled'
    if has_completion:
        return 'completed'
    if 'bekle' in key or 'new' in key:
        return 'new'
    if 'tamam' in key or 'complete' in key:
        return 'completed'
    return 'new'


class Command(BaseCommand):
    help = 'BiServisim MySQL JSON disari aktarimini bir tenant altina aktarir.'

    def add_arguments(self, parser):
        parser.add_argument('source', type=str)
        parser.add_argument('--tenant-code', default='uygar-mekanik')
        parser.add_argument('--tenant-name', default='Uygar Mekanik')
        parser.add_argument(
            '--expected-tenant-id',
            help='Mevcut tenant UUID degerini dogrular; farkliysa aktarimi durdurur.',
        )
        parser.add_argument(
            '--technician-map',
            help='Eski teknisyenleri canli kullanicilarla eslestiren JSON dosyasi.',
        )
        parser.add_argument('--admin-email')
        parser.add_argument('--admin-password')
        parser.add_argument(
            '--commit',
            action='store_true',
            help='Verileri kaydeder. Bu secenek verilmezse islem sonunda rollback yapilir.',
        )

    def handle(self, *args, **options):
        source = Path(options['source']).expanduser().resolve()
        if not source.is_file():
            raise CommandError(f'Kaynak dosya bulunamadi: {source}')

        if bool(options['admin_email']) != bool(options['admin_password']):
            raise CommandError('--admin-email ve --admin-password birlikte verilmelidir.')

        try:
            payload = json.loads(source.read_text(encoding='utf-8-sig'))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f'JSON okunamadi: {exc}') from exc

        tables = {
            entry.get('name'): entry.get('data') or []
            for entry in payload
            if entry.get('type') == 'table' and entry.get('name')
        }
        required = {'servis_musteriler', 'servis_hizmetlerimiz', 'servis_randevular'}
        missing = sorted(required - tables.keys())
        if missing:
            raise CommandError(f'Zorunlu tablolar eksik: {", ".join(missing)}')

        self.tenant_code = clean_text(options['tenant_code'], 64).lower()
        self.tenant_name = clean_text(options['tenant_name'], 200)
        self.tables = tables
        self.stats = defaultdict(int)
        self.warnings = defaultdict(int)
        self.expected_tenant_id = clean_text(options.get('expected_tenant_id'))
        self.technician_map = self._load_technician_map(options.get('technician_map'))
        if options['commit'] and self.technician_map is None:
            raise CommandError('Gercek aktarim icin --technician-map zorunludur.')

        mode = 'GERCEK AKTARIM' if options['commit'] else 'DRY-RUN'
        self.stdout.write(self.style.MIGRATE_HEADING(f'{mode}: {source.name}'))

        with transaction.atomic():
            self._run_import(options)
            if not options['commit']:
                transaction.set_rollback(True)

        self._print_report(options['commit'])

    def _run_import(self, options):
        self.tenant = Tenant.objects.filter(code=self.tenant_code).first()
        created = self.tenant is None
        if created:
            if self.expected_tenant_id:
                raise CommandError(
                    f'Beklenen tenant bulunamadi: {self.tenant_code} ({self.expected_tenant_id})'
                )
            self.tenant = Tenant.objects.create(
                code=self.tenant_code,
                name=self.tenant_name,
                app_name='Uygar Servis Yönetimi',
                is_active=True,
            )
        elif self.expected_tenant_id and str(self.tenant.id) != self.expected_tenant_id:
            raise CommandError(
                f'Tenant UUID uyusmuyor. Beklenen: {self.expected_tenant_id}, '
                f'bulunan: {self.tenant.id}'
            )
        self.stats['tenant_created'] = int(created)

        self.company, _ = CompanyConfig.objects.get_or_create(
            tenant=self.tenant,
            defaults={'name': self.tenant_name},
        )

        if options.get('admin_email'):
            self._upsert_admin(options['admin_email'], options.get('admin_password'))

        self._import_named_definitions()
        self._import_technicians()
        self._import_customers()
        self._import_products()
        self._import_services()
        self._import_operations()
        self._import_finance()

    def _load_technician_map(self, source_path):
        if not source_path:
            return None

        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise CommandError(f'Teknisyen eslestirme dosyasi bulunamadi: {source}')
        try:
            payload = json.loads(source.read_text(encoding='utf-8-sig'))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f'Teknisyen eslestirme JSON dosyasi okunamadi: {exc}') from exc

        map_tenant_code = clean_text(payload.get('tenant_code'), 64).lower()
        if map_tenant_code and map_tenant_code != self.tenant_code:
            raise CommandError(
                f'Teknisyen eslestirme dosyasi {map_tenant_code} tenantina ait; '
                f'hedef tenant {self.tenant_code}.'
            )
        map_tenant_id = clean_text(payload.get('expected_tenant_id'))
        if map_tenant_id:
            if self.expected_tenant_id and self.expected_tenant_id != map_tenant_id:
                raise CommandError('Komut ve teknisyen eslestirme dosyasindaki tenant UUID farkli.')
            self.expected_tenant_id = map_tenant_id

        result = {}
        used_targets = set()
        for entry in payload.get('technicians') or []:
            legacy_name = clean_text(entry.get('legacy_name'), 300)
            key = normalized_key(legacy_name)
            if not key:
                raise CommandError('Teknisyen eslestirmesinde legacy_name zorunludur.')
            if key in result:
                raise CommandError(f'Tekrarlanan teknisyen eslestirmesi: {legacy_name}')

            mode = clean_text(entry.get('mode')).lower()
            if mode not in {'existing', 'create'}:
                raise CommandError(f'Gecersiz teknisyen eslestirme modu: {legacy_name}')
            email = clean_text(entry.get('email'), 254).lower()
            user_id = clean_text(entry.get('user_id'))
            password_hash = clean_text(entry.get('password_hash'))
            if not email:
                raise CommandError(f'Teknisyen e-postasi eksik: {legacy_name}')
            try:
                validate_email(email)
            except ValidationError as exc:
                raise CommandError(f'Gecersiz teknisyen e-postasi: {legacy_name}') from exc
            if mode == 'existing' and not user_id:
                raise CommandError(f'Mevcut kullanici UUID eksik: {legacy_name}')
            if mode == 'create' and not password_hash:
                raise CommandError(f'Yeni kullanici parola hash degeri eksik: {legacy_name}')
            if password_hash:
                try:
                    identify_hasher(password_hash)
                except ValueError as exc:
                    raise CommandError(f'Gecersiz parola hash degeri: {legacy_name}') from exc

            target = user_id or email
            if target in used_targets:
                raise CommandError(f'Ayni kullanici birden fazla teknisyene baglanamaz: {target}')
            used_targets.add(target)
            result[key] = {
                'legacy_name': legacy_name,
                'mode': mode,
                'email': email,
                'user_id': user_id,
                'password_hash': password_hash,
            }
        return result

    def _money(self, value, limit=Decimal('99999999.99')):
        amount = parse_decimal(value)
        if abs(amount) <= limit:
            return amount

        raw_integer = re.sub(r'[^0-9]', '', clean_text(value).split('.')[0])
        candidate = Decimal(raw_integer[-6:] or '0').quantize(Decimal('0.01'))
        if candidate == 0:
            leading = raw_integer.rstrip('0')
            if leading and len(leading) <= 3:
                candidate = (Decimal(leading) * 1000).quantize(Decimal('0.01'))
        if Decimal('0.00') < candidate <= limit:
            self.warnings['corrected_oversized_amounts'] += 1
            return candidate

        self.warnings['skipped_oversized_amounts'] += 1
        return Decimal('0.00')

    def _upsert_admin(self, email, password):
        email = clean_text(email, 254).lower()
        existing = User.objects.filter(email=email).first()
        if existing and existing.tenant_id != self.tenant.id:
            raise CommandError('Yonetici e-postasi baska bir tenant tarafindan kullaniliyor.')

        if existing:
            self.stats['admin_preserved'] += 1
            return existing

        admin_id = legacy_uuid(self.tenant_code, 'admin', email)
        admin = User(
            pk=admin_id,
            tenant=self.tenant,
            email=email,
            first_name='Uygar',
            last_name='Yönetici',
            user_type='admin',
            approval_status='approved',
            is_active=True,
            is_staff=True,
        )
        admin.set_password(password)
        admin.save()
        self.stats['admin_created'] += 1

    def _import_named_definitions(self):
        device_names = [row.get('cihaztipi') for row in self.tables.get('cihaztipleri', [])]
        device_names.extend(row.get('uruntipi') for row in self.tables.get('servis_randevular', []))
        device_names.extend(row.get('urun_tipi') for row in self.tables.get('servis_hizmetlerimiz', []))
        self.device_types = self._upsert_named_models(DeviceType, device_names)

        brand_names = [row.get('marka_adi') for row in self.tables.get('markalar', [])]
        brand_names.extend(row.get('urunmarka') for row in self.tables.get('servis_randevular', []))
        brand_names.extend(row.get('urun_marka') for row in self.tables.get('servis_hizmetlerimiz', []))
        self.brands = self._upsert_named_models(Brand, brand_names)

        self.stats['device_types'] = len(self.device_types)
        self.stats['brands'] = len(self.brands)

    def _upsert_named_models(self, model, names):
        result = {
            normalized_key(item.name): item
            for item in model.objects.filter(tenant=self.tenant)
        }
        for raw_name in names:
            name = clean_text(raw_name, 50)
            key = normalized_key(name)
            if not key or key in result:
                continue
            item = model.objects.create(tenant=self.tenant, name=name)
            result[key] = item
        return result

    def _import_technicians(self):
        names = {
            clean_text(row.get('teknisyen_adi_soyadi'), 300)
            for row in self.tables.get('servis_hizmetlerimiz', [])
            if clean_text(row.get('teknisyen_adi_soyadi'))
        }
        names.update(
            clean_text(row.get('teknisyenadi'), 300)
            for row in self.tables.get('malzeme_arac_kullanilan', [])
            if clean_text(row.get('teknisyenadi'))
        )

        if self.technician_map is not None:
            missing = sorted(
                name for name in names
                if normalized_key(name) not in self.technician_map
            )
            if missing:
                raise CommandError(
                    'Teknisyen eslestirmesi eksik: ' + ', '.join(missing)
                )

        self.technicians = {}
        for name in sorted(names, key=normalized_key):
            key = normalized_key(name)
            if not key:
                continue
            first_name, last_name = split_name(name)
            if self.technician_map is None:
                digest = hashlib.sha1(name.encode('utf-8')).hexdigest()[:12]
                entry = {
                    'mode': 'create',
                    'email': f'legacy-tech-{digest}@uygar.invalid',
                    'user_id': '',
                    'password_hash': '',
                }
            else:
                entry = self.technician_map[key]

            user = self._resolve_technician_user(entry, key, first_name, last_name)
            technician = Technician.objects.filter(user=user).first()
            if technician and technician.tenant_id != self.tenant.id:
                raise CommandError(
                    f'Teknisyen profili baska tenant kaydina ait: {entry["email"]}'
                )
            if not technician:
                technician = Technician.objects.create(
                    id=legacy_uuid(self.tenant_code, 'technician-profile', key),
                    user=user,
                    tenant=self.tenant,
                    hire_date=date.today(),
                    is_online=False,
                )
                self.stats['technician_profiles_created'] += 1
            else:
                self.stats['technician_profiles_preserved'] += 1
            self.technicians[key] = technician

        self.stats['legacy_technicians'] = len(self.technicians)

    def _resolve_technician_user(self, entry, key, first_name, last_name):
        email = entry['email']
        if entry['mode'] == 'existing':
            user = User.objects.filter(pk=entry['user_id']).first()
            if not user:
                raise CommandError(f'Mevcut kullanici bulunamadi: {email}')
            if user.email.lower() != email:
                raise CommandError(
                    f'Kullanici UUID ve e-posta uyusmuyor: {entry["user_id"]} / {email}'
                )
            if user.tenant_id != self.tenant.id:
                raise CommandError(f'Kullanici baska tenant kaydina ait: {email}')
            self.stats['technician_users_preserved'] += 1
            return user

        user = User.objects.filter(email__iexact=email).first()
        if user:
            if user.tenant_id != self.tenant.id:
                raise CommandError(f'Kullanici e-postasi baska tenantta kayitli: {email}')
            self.stats['technician_users_preserved'] += 1
            return user

        user_id = legacy_uuid(self.tenant_code, 'technician-user', key)
        conflicting_user = User.objects.filter(pk=user_id).first()
        if conflicting_user:
            raise CommandError(
                f'Teknisyen UUID baska kullaniciyla cakisti: {conflicting_user.email}'
            )

        user = User(
            id=user_id,
            tenant=self.tenant,
            email=email,
            first_name=first_name,
            last_name=last_name,
            user_type='technician',
            approval_status='approved',
            is_active=bool(entry['password_hash']),
            is_staff=False,
            password=entry['password_hash'],
        )
        if not entry['password_hash']:
            user.set_unusable_password()
        user.save()
        self.stats['technician_users_created'] += 1
        return user

    def _customer_address(self, row):
        direct = clean_text(row.get('musteri_adresi') or row.get('acikadres'))
        if direct:
            return direct
        return clean_text(' '.join(filter(None, [
            clean_text(row.get('ilce')),
            clean_text(row.get('mahalle')),
            clean_text(row.get('sokak')),
            clean_text(row.get('kapino')),
        ])))

    def _customer_note(self, row, codes):
        parts = [f'BiServisim müşteri kodu: {", ".join(sorted(codes))}']
        phone_two = CustomerSerializer.normalize_phone(row.get('musteri_telefonu2'))
        if phone_two:
            parts.append(f'İkinci telefon: {phone_two}')
        tax_office = clean_text(row.get('vergi_dairesi'))
        tax_number = clean_text(row.get('vergi_numarasi'))
        if tax_office:
            parts.append(f'Vergi dairesi: {tax_office}')
        if tax_number:
            parts.append(f'Vergi numarası: {tax_number}')
        return '\n'.join(parts)

    def _import_customers(self):
        source_by_code = {}
        for table_name in ('servis_musteriler', 'servis_musteriler2'):
            for row in self.tables.get(table_name, []):
                code = clean_text(row.get('musteri_kodu'))
                if code and code not in source_by_code:
                    source_by_code[code] = row

        for row in self.tables.get('servis_hizmetlerimiz', []):
            code = clean_text(row.get('musteri_kodu')) or f'BIS-H{clean_text(row.get("id"))}'
            if code and code not in source_by_code:
                source_by_code[code] = {
                    'musteri_kodu': code,
                    'musteri_adisoyadi': row.get('must_adi') or 'İsimsiz Eski Müşteri',
                    'musteri_telefonu': row.get('must_telefon'),
                    'musteri_telefonu2': row.get('must_telefon2'),
                }

        for row in self.tables.get('servis_randevular', []):
            code = clean_text(row.get('randevu_musterikodu'))
            if code and code not in source_by_code:
                source_by_code[code] = {
                    'musteri_kodu': code,
                    'musteri_adisoyadi': f'Eski Müşteri {code}',
                }

        canonical = {}
        code_to_id = {}
        codes_by_id = defaultdict(set)
        for code in sorted(source_by_code):
            row = source_by_code[code]
            phone = CustomerSerializer.normalize_phone(row.get('musteri_telefonu'))
            source_key = f'phone:{phone}' if phone else f'code:{code}'
            customer_id = legacy_uuid(self.tenant_code, 'customer', source_key)
            code_to_id[code] = customer_id
            codes_by_id[customer_id].add(code)

            current = canonical.get(customer_id)
            candidate = {
                'id': customer_id,
                'full_name': clean_text(row.get('musteri_adisoyadi'), 255),
                'phone_number': phone or None,
                'email': clean_text(row.get('musteriemail'), 254) or None,
                'address': self._customer_address(row) or None,
                'row': row,
            }
            if not current or sum(bool(value) for value in candidate.values()) > sum(bool(value) for value in current.values()):
                canonical[customer_id] = candidate

        objects = []
        for customer_id, item in canonical.items():
            objects.append(Customer(
                id=customer_id,
                tenant=self.tenant,
                full_name=item['full_name'] or 'İsimsiz Eski Müşteri',
                phone_number=item['phone_number'],
                email=item['email'],
                address=item['address'],
                note=self._customer_note(item['row'], codes_by_id[customer_id]),
                is_deleted=False,
            ))

        Customer.objects.bulk_create(objects, batch_size=500, ignore_conflicts=True)
        Customer.objects.bulk_update(
            objects,
            ['tenant', 'full_name', 'phone_number', 'email', 'address', 'note', 'is_deleted'],
            batch_size=500,
        )
        self.customers = Customer.objects.in_bulk(canonical.keys())
        self.customer_by_code = {
            code: self.customers[customer_id]
            for code, customer_id in code_to_id.items()
            if customer_id in self.customers
        }
        self.stats['customers'] = len(self.customers)
        self.stats['merged_customer_codes'] = len(source_by_code) - len(self.customers)

    def _import_products(self):
        rows = list(self.tables.get('malzeme_listesi', []))
        source_codes = {clean_text(row.get('stokkodu')) for row in rows if clean_text(row.get('stokkodu'))}
        for usage in self.tables.get('malzeme_arac_kullanilan', []):
            code = clean_text(usage.get('stokkodu'))
            if code and code not in source_codes:
                rows.append({
                    'id': f'inferred-{code}',
                    'stokkodu': code,
                    'stokadi': f'Eski Malzeme {code}',
                    'stoktipi': usage.get('stoktipi') or 'Malzeme',
                    'fiyat_satis': usage.get('satis_fiyati'),
                    'depoadedi': 0,
                    'durum': 'PASIF',
                })
                source_codes.add(code)
                self.warnings['inferred_products'] += 1

        category_names = {clean_text(row.get('stoktipi'), 100) or 'Malzeme' for row in rows}
        categories = {}
        for name in sorted(category_names, key=normalized_key):
            category, _ = ProductCategory.objects.update_or_create(
                pk=legacy_uuid(self.tenant_code, 'product-category', normalized_key(name)),
                defaults={'tenant': self.tenant, 'name': name},
            )
            categories[normalized_key(name)] = category

        objects = []
        self.product_id_by_code = {}
        for row in rows:
            source_id = clean_text(row.get('id')) or clean_text(row.get('stokkodu'))
            code = clean_text(row.get('stokkodu'), 50) or f'LEGACY-{source_id}'[:50]
            product_id = legacy_uuid(self.tenant_code, 'product', source_id)
            quantity = parse_positive_int(row.get('depoadedi') or 0, default=0)
            active = 'PASIF' not in clean_text(row.get('durum')).upper()
            product = Product(
                id=product_id,
                tenant=self.tenant,
                category=categories.get(normalized_key(row.get('stoktipi') or 'Malzeme')),
                name=clean_text(row.get('stokadi'), 200) or f'Eski Ürün {source_id}',
                code=code,
                description=f'BiServisim stok kaydı #{source_id}',
                price=self._money(row.get('fiyat_satis')),
                stock_quantity=quantity,
                status='in_stock' if quantity > 0 else 'out_stock',
                is_active=active,
            )
            objects.append(product)
            if clean_text(row.get('stokkodu')):
                self.product_id_by_code[clean_text(row.get('stokkodu'))] = product_id

        Product.objects.bulk_create(objects, batch_size=500, ignore_conflicts=True)
        Product.objects.bulk_update(
            objects,
            ['tenant', 'category', 'name', 'code', 'description', 'price', 'stock_quantity', 'status', 'is_active'],
            batch_size=500,
        )
        self.products = Product.objects.in_bulk([item.id for item in objects])
        self.stats['products'] = len(self.products)

    def _service_datetime(self, appointment, completion):
        result = aware_datetime(
            appointment.get('randevu_tarihi') if appointment else None,
            appointment.get('randevu_saati') if appointment else None,
        )
        if result:
            return result
        result = aware_datetime(
            completion.get('ziyaret_tarihi') if completion else None,
            completion.get('bitis_saati') if completion else None,
        )
        if result:
            return result
        result = aware_datetime(appointment.get('randevu_olus_zamani') if appointment else None)
        if result:
            return result
        tracking_code = clean_text(completion.get('ariza_takip_kodu') if completion else None)
        tracking_match = re.search(r'AK-(\d{4})(\d{2})(\d{2})', tracking_code)
        if tracking_match:
            try:
                parsed = date(*(int(part) for part in tracking_match.groups()))
                return timezone.make_aware(
                    datetime.combine(parsed, time(12, 0)),
                    timezone.get_current_timezone(),
                )
            except ValueError:
                pass
        self.warnings['invalid_service_dates'] += 1
        return timezone.make_aware(datetime(2019, 9, 1, 12, 0), timezone.get_current_timezone())

    def _import_services(self):
        completion_groups = defaultdict(list)
        orphan_completions = []
        for row in self.tables.get('servis_hizmetlerimiz', []):
            appointment_id = clean_text(row.get('randevu_num'))
            if appointment_id:
                completion_groups[appointment_id].append(row)
            else:
                orphan_completions.append(row)

        appointments = {
            clean_text(row.get('id')): row
            for row in self.tables.get('servis_randevular', [])
            if clean_text(row.get('id'))
        }
        specs = [
            (appointment_id, row, completion_groups.get(appointment_id, []))
            for appointment_id, row in appointments.items()
        ]
        specs.extend(
            (f'H{clean_text(row.get("id"))}', None, [row])
            for row in orphan_completions
        )

        statuses = {}
        for code, name, color, order, terminal in (
            ('new', 'Yeni', '#16A34A', 10, False),
            ('completed', 'Tamamlandı', '#16A34A', 50, True),
            ('cancelled', 'İptal Edildi', '#DC2626', 60, True),
        ):
            status, _ = ServiceStatus.objects.update_or_create(
                tenant=self.tenant,
                code=code,
                defaults={
                    'name': name,
                    'color': color,
                    'sort_order': order,
                    'is_terminal': terminal,
                    'is_active': True,
                },
            )
            statuses[code] = status

        objects = []
        intended_dates = {}
        self.service_id_by_appointment = {}
        self.service_id_by_legacy_service = {}
        self.completions_by_appointment = completion_groups
        for source_key, appointment, completions in specs:
            completion = sorted(completions, key=lambda row: int(clean_text(row.get('id')) or 0))[-1] if completions else {}
            appointment = appointment or {}
            customer_code = clean_text(
                appointment.get('randevu_musterikodu') or completion.get('musteri_kodu')
            )
            if not customer_code and completion:
                customer_code = f'BIS-H{clean_text(completion.get("id"))}'
            customer = self.customer_by_code.get(customer_code)
            scheduled_at = self._service_datetime(appointment, completion)
            created_at = aware_datetime(appointment.get('randevu_olus_zamani')) or scheduled_at
            service_id = legacy_uuid(self.tenant_code, 'service', source_key)
            code = status_code(appointment.get('randevu_durumu'), bool(completions))
            device_type = self.device_types.get(normalized_key(
                appointment.get('uruntipi') or completion.get('urun_tipi')
            ))
            brand = self.brands.get(normalized_key(
                appointment.get('urunmarka') or completion.get('urun_marka')
            ))
            technician = self.technicians.get(normalized_key(completion.get('teknisyen_adi_soyadi')))
            receipt_suffix = re.sub(r'[^A-Za-z0-9]', '', source_key)
            receipt_prefix = hashlib.sha1(self.tenant_code.encode('utf-8')).hexdigest()[:4].upper()
            receipt_number = f'BS-{receipt_prefix}-{receipt_suffix}'[:20]
            full_name = clean_text(completion.get('must_adi'), 200)
            phone = CustomerSerializer.normalize_phone(completion.get('must_telefon'))
            address = clean_text(getattr(customer, 'address', None))

            service = Service(
                id=service_id,
                tenant=self.tenant,
                customer=customer,
                customer_phone=phone or getattr(customer, 'phone_number', None),
                customer_full_name=full_name or getattr(customer, 'full_name', None) or 'İsimsiz Eski Müşteri',
                customer_address=address,
                fault_description=clean_text(
                    appointment.get('basvurunedeni') or completion.get('basvuru_ariza_sebep')
                ),
                device_type=device_type,
                device_brand=brand,
                technician=technician,
                status=statuses[code],
                receipt_number=receipt_number,
                scheduled_date=scheduled_at,
            )
            service.created_at = created_at
            service.updated_at = created_at
            objects.append(service)
            intended_dates[service_id] = (created_at, created_at)
            if not source_key.startswith('H'):
                self.service_id_by_appointment[source_key] = service_id
            for completion_row in completions:
                legacy_service_id = clean_text(completion_row.get('id'))
                if legacy_service_id:
                    self.service_id_by_legacy_service[legacy_service_id] = service_id

        Service.objects.bulk_create(objects, batch_size=300, ignore_conflicts=True)
        for item in objects:
            item.created_at, item.updated_at = intended_dates[item.id]
        Service.objects.bulk_update(
            objects,
            [
                'tenant', 'customer', 'customer_phone', 'customer_full_name', 'customer_address',
                'fault_description', 'device_type', 'device_brand', 'technician', 'status',
                'receipt_number', 'scheduled_date', 'created_at', 'updated_at',
            ],
            batch_size=300,
        )
        self.services = Service.objects.in_bulk([item.id for item in objects])
        self.stats['services'] = len(self.services)

    def _import_operations(self):
        objects = []
        usage_totals = defaultdict(lambda: Decimal('0.00'))

        for row in self.tables.get('malzeme_arac_kullanilan', []):
            appointment_id = clean_text(row.get('randevu_num'))
            service_id = self.service_id_by_appointment.get(appointment_id)
            service = self.services.get(service_id)
            if not service:
                self.warnings['unmatched_operations'] += 1
                continue
            product_id = self.product_id_by_code.get(clean_text(row.get('stokkodu')))
            product = self.products.get(product_id)
            quantity = parse_positive_int(row.get('montajadedi'), default=1)
            unit_price = self._money(row.get('satis_fiyati'))
            line_total = self._money(row.get('toplam_tutar')) or unit_price * quantity
            usage_totals[appointment_id] += line_total
            if quantity and line_total and not unit_price:
                unit_price = (line_total / quantity).quantize(Decimal('0.01'))
            objects.append(ServiceOperations(
                id=legacy_uuid(self.tenant_code, 'service-operation-usage', row.get('id')),
                tenant=self.tenant,
                service=service,
                product=product,
                name=clean_text(getattr(product, 'name', None) or row.get('stoktipi'), 255) or 'Eski İşlem',
                description=f'BiServisim işlem kaydı #{clean_text(row.get("id"))}'[:255],
                quantity=quantity,
                unit_price=unit_price,
            ))

        for appointment_id, completions in self.completions_by_appointment.items():
            service_id = self.service_id_by_appointment.get(appointment_id)
            service = self.services.get(service_id)
            if not service:
                continue
            legacy_total = max((self._money(row.get('genel_toplam')) for row in completions), default=Decimal('0.00'))
            residual = legacy_total - usage_totals[appointment_id]
            if residual < 0:
                self.warnings['operation_total_above_service_total'] += 1
                residual = Decimal('0.00')

            priced = False
            for row in completions:
                description = clean_text(row.get('tekniksyen_yapilan_islem'), 255)
                if not description and not residual:
                    continue
                price = residual if not priced else Decimal('0.00')
                priced = priced or bool(price)
                objects.append(ServiceOperations(
                    id=legacy_uuid(self.tenant_code, 'service-operation-work', row.get('id')),
                    tenant=self.tenant,
                    service=service,
                    name='Yapılan işlem',
                    description=description,
                    quantity=1,
                    unit_price=price,
                ))

        ServiceOperations.objects.bulk_create(objects, batch_size=500, ignore_conflicts=True)
        ServiceOperations.objects.bulk_update(
            objects,
            ['tenant', 'service', 'product', 'name', 'description', 'quantity', 'unit_price'],
            batch_size=500,
        )
        self.stats['service_operations'] = len(objects)

    def _payment_method(self, channel):
        channel_key = normalized_key(channel)
        if any(token in channel_key for token in ('kart', 'pos', 'card')):
            name = 'Kredi Kartı'
        elif any(token in channel_key for token in ('banka', 'havale', 'eft', 'iban')):
            name = 'Banka'
        else:
            name = 'Nakit'
        if not hasattr(self, 'payment_methods'):
            self.payment_methods = {}
        if name not in self.payment_methods:
            self.payment_methods[name], _ = PaymentMethod.objects.get_or_create(
                tenant=self.tenant,
                name=name,
            )
        return self.payment_methods[name]

    def _import_finance(self):
        account, _ = Account.objects.update_or_create(
            pk=legacy_uuid(self.tenant_code, 'account', 'legacy-cash'),
            defaults={
                'tenant': self.tenant,
                'company': self.company,
                'name': 'BiServisim Eski Kasa',
                'account_type': 'cash',
                'balance': Decimal('0.00'),
            },
        )
        categories = {}
        transactions = []
        payments = []
        payment_dates = {}

        for row in self.tables.get('kasa', []):
            amount = abs(self._money(row.get('gider_gelir_tutar')))
            if amount <= 0:
                self.warnings['zero_finance_rows'] += 1
                continue
            row_id = clean_text(row.get('id'))
            type_key = normalized_key(row.get('gider_gelir'))
            transaction_type = 'expense' if 'gider' in type_key else 'income'
            category_name = clean_text(row.get('gider_gelir_turu'), 100) or (
                'Eski Gider' if transaction_type == 'expense' else 'Eski Gelir'
            )
            category_key = (transaction_type, normalized_key(category_name))
            if category_key not in categories:
                category, _ = TransactionCategory.objects.update_or_create(
                    pk=legacy_uuid(self.tenant_code, 'transaction-category', ':'.join(category_key)),
                    defaults={
                        'tenant': self.tenant,
                        'company': self.company,
                        'name': category_name,
                        'type': transaction_type,
                    },
                )
                categories[category_key] = category

            description = clean_text(row.get('gider_gelir_aciklama'))
            appointment_match = re.search(r'(\d+)\s+NUMARALI', description.upper())
            appointment_id = appointment_match.group(1) if appointment_match else None
            service_id = (
                self.service_id_by_legacy_service.get(appointment_id)
                or self.service_id_by_appointment.get(appointment_id)
            )
            service = self.services.get(service_id)
            row_date = aware_datetime(row.get('tarih')) or timezone.make_aware(
                datetime(2000, 1, 1, 12, 0), timezone.get_current_timezone()
            )
            is_active = 'PASIF' not in clean_text(row.get('gider_gelir_durum')).upper()
            transactions.append(Transaction(
                id=legacy_uuid(self.tenant_code, 'transaction', row_id),
                tenant=self.tenant,
                company=self.company,
                transaction_type=transaction_type,
                account=account,
                category=categories[category_key],
                amount=amount,
                date=row_date,
                description=description,
                receipt_number=f'BIS-KASA-{row_id}'[:50],
                service=service,
                is_retrieved=not is_active,
            ))

            if transaction_type == 'income' and service:
                payment_id = legacy_uuid(self.tenant_code, 'service-payment', row_id)
                payment = ServicePayment(
                    id=payment_id,
                    tenant=self.tenant,
                    service=service,
                    amount=amount,
                    payment_method=self._payment_method(row.get('odemekanali')),
                    note=description,
                )
                payment.created_at = row_date
                payments.append(payment)
                payment_dates[payment_id] = row_date

        Transaction.objects.bulk_create(transactions, batch_size=400, ignore_conflicts=True)
        Transaction.objects.bulk_update(
            transactions,
            [
                'tenant', 'company', 'transaction_type', 'account', 'category', 'amount',
                'date', 'description', 'receipt_number', 'service', 'is_retrieved',
            ],
            batch_size=400,
        )
        ServicePayment.objects.bulk_create(payments, batch_size=400, ignore_conflicts=True)
        for payment in payments:
            payment.created_at = payment_dates[payment.id]
        ServicePayment.objects.bulk_update(
            payments,
            ['tenant', 'service', 'amount', 'payment_method', 'note', 'created_at'],
            batch_size=400,
        )

        income = Transaction.objects.filter(
            account=account,
            transaction_type='income',
            is_retrieved=False,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        expense = Transaction.objects.filter(
            account=account,
            transaction_type='expense',
            is_retrieved=False,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        Account.objects.filter(pk=account.pk).update(balance=income - expense)

        self.stats['accounting_transactions'] = len(transactions)
        self.stats['service_payments'] = len(payments)
        self.stats['transaction_categories'] = len(categories)

    def _print_report(self, committed):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Aktarim raporu'))
        for key in sorted(self.stats):
            self.stdout.write(f'  {key}: {self.stats[key]}')
        for key in sorted(self.warnings):
            self.stdout.write(self.style.WARNING(f'  UYARI {key}: {self.warnings[key]}'))

        ignored = {
            name: len(rows)
            for name, rows in self.tables.items()
            if name not in SUPPORTED_TABLES and rows
        }
        if ignored:
            self.stdout.write(self.style.WARNING('  Uygulamada karsiligi olmayan tablolar:'))
            for name, count in sorted(ignored.items()):
                self.stdout.write(f'    {name}: {count}')

        if committed:
            self.stdout.write(self.style.SUCCESS('Aktarim veritabanina kaydedildi.'))
        else:
            self.stdout.write(self.style.WARNING('DRY-RUN tamamlandi; tum degisiklikler geri alindi.'))
