import random
from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from faker import Faker

from customers.models import Customer
from services.models import Service
from tenants.models import Tenant
from technicians.models import (
    LocationLog,
    Technician,
    TechnicianAttendance,
    TechnicianLocation,
    TechnicianShift,
)

TURKISH_CITIES = [
    {"name": "İstanbul - Kadıköy", "lat": 40.992881, "lng": 29.027502},
    {"name": "İstanbul - Beşiktaş", "lat": 41.042686, "lng": 29.007920},
    {"name": "İstanbul - Şişli", "lat": 41.060181, "lng": 28.987110},
    {"name": "Ankara - Çankaya", "lat": 39.918060, "lng": 32.855390},
    {"name": "Ankara - Yenimahalle", "lat": 39.973220, "lng": 32.812450},
    {"name": "İzmir - Konak", "lat": 38.418850, "lng": 27.128720},
    {"name": "İzmir - Karşıyaka", "lat": 38.462110, "lng": 27.113450},
    {"name": "Bursa - Osmangazi", "lat": 40.188510, "lng": 29.061020},
    {"name": "Antalya - Muratpaşa", "lat": 36.896900, "lng": 30.713320},
    {"name": "Eskişehir - Tepebaşı", "lat": 39.776700, "lng": 30.520600},
    {"name": "Konya - Selçuklu", "lat": 37.874600, "lng": 32.493200},
    {"name": "Kayseri - Melikgazi", "lat": 38.722500, "lng": 35.487500},
    {"name": "Trabzon - Ortahisar", "lat": 41.002700, "lng": 39.716800},
    {"name": "Samsun - Atakum", "lat": 41.286700, "lng": 36.330000},
    {"name": "Gaziantep - Şahinbey", "lat": 37.066000, "lng": 37.383300},
    {"name": "Adana - Seyhan", "lat": 36.985000, "lng": 35.321100},
    {"name": "Mersin - Yenişehir", "lat": 36.812100, "lng": 34.641500},
    {"name": "Denizli - Merkez", "lat": 37.776500, "lng": 29.086400},
    {"name": "Kocaeli - İzmit", "lat": 40.765400, "lng": 29.940800},
    {"name": "Sakarya - Adapazarı", "lat": 40.780600, "lng": 30.403300},
]


LEAVE_NOTES = [
    "Yıllık izin kullanıldı.",
    "Mazeret izni alındı.",
    "Sağlık raporu mevcut.",
    "Ailevi sebepler.",
    "Doktor kontrolü.",
]

SICK_NOTES = [
    "Hafif ateş, doktor önerisiyle evde dinleniyor.",
    "Grip, yatak istirahati.",
    "Bel ağrısı, fizik tedavi.",
    "Migren krizi.",
]

WORK_NOTES = [
    None, None, None,
    "Mesaiye geç katıldı.",
    "Erken çıkış yaptı.",
    "Sahada yoğun gün.",
    "Servis tamamlandı.",
    "Eğitim saatine katıldı.",
]


class Command(BaseCommand):
    help = "Tum tenantlar icin teknisyen konum, mesai, izin ve devam kayitlari olusturur."

    def add_arguments(self, parser):
        parser.add_argument("--locations", type=int, default=5, help="Her teknisyen icin konum kaydi (varsayilan: 5).")
        parser.add_argument("--shifts", type=int, default=20, help="Her teknisyen icin mesai kaydi (varsayilan: 20).")
        parser.add_argument("--attendances", type=int, default=25, help="Her teknisyen icin devam kaydi (varsayilan: 25).")
        parser.add_argument("--location-logs", type=int, default=8, help="Her teknisyen icin konum logu (varsayilan: 8).")
        parser.add_argument("--tenant-id", type=str, default=None, help="Sadece belirli bir tenant.")
        parser.add_argument("--seed", type=int, default=None, help="Tekrarlanabilir uretim icin seed.")
        parser.add_argument("--wipe", action="store_true", help="Mevcut konum/mesai/devam loglarini sil.")

    def handle(self, *args, **options):
        n_locations = options["locations"]
        n_shifts = options["shifts"]
        n_attendances = options["attendances"]
        n_logs = options["location_logs"]
        tenant_id = options["tenant_id"]
        seed = options["seed"]
        wipe = options["wipe"]

        if min(n_locations, n_shifts, n_attendances, n_logs) < 0:
            self.stderr.write(self.style.ERROR("Sayilar negatif olamaz."))
            return

        faker = Faker("tr_TR")
        if seed is not None:
            Faker.seed(seed)
            random.seed(seed)

        tenants_qs = Tenant.objects.all().order_by("name")
        if tenant_id:
            tenants_qs = tenants_qs.filter(id=tenant_id)

        if not tenants_qs.exists():
            self.stderr.write(self.style.ERROR("Hic tenant bulunamadi."))
            return

        total = {"locations": 0, "shifts": 0, "attendances": 0, "logs": 0}

        for tenant in tenants_qs:
            if wipe:
                d_loc, _ = TechnicianLocation.objects.filter(tenant=tenant).delete()
                d_sh, _ = TechnicianShift.objects.filter(tenant=tenant).delete()
                d_at, _ = TechnicianAttendance.objects.filter(tenant=tenant).delete()
                d_lg, _ = LocationLog.objects.filter(tenant=tenant).delete()
                self.stdout.write(self.style.WARNING(
                    f"{tenant.name} ({tenant.id}): temizlendi - "
                    f"{d_loc} konum, {d_sh} mesai, {d_at} devam, {d_lg} konum logu"
                ))

            technicians = list(
                Technician.objects.filter(tenant=tenant).select_related("user")
            )
            if not technicians:
                self.stdout.write(self.style.WARNING(
                    f"{tenant.name}: teknisyen yok, atlandi."
                ))
                continue

            customers = list(Customer.objects.filter(tenant=tenant, is_deleted=False))
            services = list(Service.objects.filter(customer__tenant=tenant)) if customers else []

            counts = self._create_for_tenant(
                faker, tenant, technicians, customers, services,
                n_locations, n_shifts, n_attendances, n_logs
            )
            for key, val in counts.items():
                total[key] += val
            self.stdout.write(self.style.SUCCESS(
                f"{tenant.name} ({tenant.id}): "
                f"{counts['locations']} konum, {counts['shifts']} mesai, "
                f"{counts['attendances']} devam, {counts['logs']} konum logu olusturuldu"
            ))

        self.stdout.write(self.style.SUCCESS(
            f"Islem tamam. Toplam: {total['locations']} konum, "
            f"{total['shifts']} mesai, {total['attendances']} devam, {total['logs']} konum logu"
        ))

    def _create_for_tenant(self, faker, tenant, technicians, customers, services,
                           n_locations, n_shifts, n_attendances, n_logs):
        counts = {"locations": 0, "shifts": 0, "attendances": 0, "logs": 0}

        with transaction.atomic():
            for tech in technicians:
                counts["locations"] += self._create_locations(tech, tenant, n_locations)
                counts["shifts"] += self._create_shifts(tech, tenant, faker, n_shifts)
                counts["attendances"] += self._create_attendances(tech, tenant, faker, n_attendances)
                counts["logs"] += self._create_location_logs(
                    tech, tenant, customers, services, faker, n_logs
                )
        return counts

    def _create_locations(self, technician, tenant, target):
        user = technician.user
        created = 0
        for i in range(target):
            city = random.choice(TURKISH_CITIES)
            jitter_lat = city["lat"] + random.uniform(-0.05, 0.05)
            jitter_lng = city["lng"] + random.uniform(-0.05, 0.05)
            try:
                TechnicianLocation.objects.create(
                    tenant=tenant,
                    technician=user,
                    location=city["name"],
                    latitude=f"{jitter_lat:.6f}",
                    longitude=f"{jitter_lng:.6f}",
                )
                created += 1
            except Exception as exc:
                self.stdout.write(self.style.WARNING(
                    f"Konum olusturulamadi ({user.email}): {exc}"
                ))
        return created

    def _create_shifts(self, technician, tenant, faker, target):
        user = technician.user
        created = 0
        now = timezone.now()
        for i in range(target):
            days_offset = random.randint(0, 30)
            shift_date = now - timedelta(days=days_offset)
            start_hour = random.randint(7, 11)
            start_min = random.choice([0, 15, 30, 45])
            duration_hours = random.choice([6, 7, 8, 8, 9, 10])
            start_dt = shift_date.replace(
                hour=start_hour, minute=start_min, second=0, microsecond=0
            )
            end_dt = start_dt + timedelta(hours=duration_hours)
            try:
                shift = TechnicianShift.objects.create(
                    tenant=tenant,
                    technician=user,
                    date=shift_date.date(),
                    start_time=start_dt,
                    end_time=end_dt,
                )
                TechnicianShift.objects.filter(pk=shift.pk).update(
                    created_at=start_dt - timedelta(days=1),
                    updated_at=start_dt,
                )
                created += 1
            except Exception as exc:
                self.stdout.write(self.style.WARNING(
                    f"Mesai olusturulamadi ({user.email}): {exc}"
                ))
        return created

    def _create_attendances(self, technician, tenant, faker, target):
        created = 0
        today = timezone.localdate()
        for i in range(target):
            days_offset = random.randint(0, 45)
            att_date = today - timedelta(days=days_offset)
            existing = TechnicianAttendance.objects.filter(
                technician=technician, date=att_date
            ).first()
            if existing:
                continue

            status_weights = [
                (TechnicianAttendance.STATUS_WORKED, 70),
                (TechnicianAttendance.STATUS_LEAVE, 10),
                (TechnicianAttendance.STATUS_SICK, 8),
                (TechnicianAttendance.STATUS_OFFDAY, 7),
                (TechnicianAttendance.STATUS_ABSENT, 5),
            ]
            statuses, weights = zip(*status_weights)
            status = random.choices(statuses, weights=weights, k=1)[0]

            start_time = None
            end_time = None
            note = None
            source = TechnicianAttendance.SOURCE_MANUAL

            if status == TechnicianAttendance.STATUS_WORKED:
                start_time = time(hour=random.randint(8, 10), minute=random.choice([0, 15, 30, 45]))
                end_time = time(hour=random.randint(17, 19), minute=random.choice([0, 15, 30, 45]))
                note = random.choice(WORK_NOTES)
                if random.random() < 0.3:
                    source = TechnicianAttendance.SOURCE_SHIFT
            elif status == TechnicianAttendance.STATUS_LEAVE:
                note = random.choice(LEAVE_NOTES)
            elif status == TechnicianAttendance.STATUS_SICK:
                note = random.choice(SICK_NOTES)
            elif status == TechnicianAttendance.STATUS_OFFDAY:
                note = "Resmi tatil."
            elif status == TechnicianAttendance.STATUS_ABSENT:
                note = "Devamsizlik."

            try:
                record = TechnicianAttendance.objects.create(
                    tenant=tenant,
                    technician=technician,
                    date=att_date,
                    status=status,
                    start_time=start_time,
                    end_time=end_time,
                    note=note,
                    source=source,
                )
                created += 1
            except Exception as exc:
                self.stdout.write(self.style.WARNING(
                    f"Devam kaydi olusturulamadi ({technician.id}/{att_date}): {exc}"
                ))
        return created

    def _create_location_logs(self, technician, tenant, customers, services, faker, target):
        if not customers:
            return 0
        user = technician.user
        created = 0
        now = timezone.now()
        for i in range(target):
            customer = random.choice(customers)
            service = random.choice(services) if services and random.random() < 0.5 else None
            customer_lat = 41.0 + random.uniform(-0.5, 0.5)
            customer_lng = 29.0 + random.uniform(-0.5, 0.5)
            tech_lat = customer_lat + random.uniform(-0.01, 0.01)
            tech_lng = customer_lng + random.uniform(-0.01, 0.01)
            distance = random.uniform(20, 1500)
            days_ago = random.randint(0, 30)
            minutes_ago = random.randint(0, 24 * 60)
            arrived = now - timedelta(days=days_ago, minutes=minutes_ago)
            event = random.choice([
                LocationLog.EVENT_ARRIVED,
                LocationLog.EVENT_STAYING,
                LocationLog.EVENT_LEFT,
            ])
            last_seen = arrived + timedelta(minutes=random.randint(10, 90))
            left_at = None
            if event == LocationLog.EVENT_LEFT:
                left_at = last_seen + timedelta(minutes=random.randint(5, 60))
            try:
                log = LocationLog.objects.create(
                    tenant=tenant,
                    user=user,
                    technician=technician,
                    service=service,
                    customer=customer,
                    latitude=tech_lat,
                    longitude=tech_lng,
                    customer_latitude=customer_lat,
                    customer_longitude=customer_lng,
                    last_distance_meters=distance,
                    arrived_at=arrived,
                    last_seen_at=last_seen,
                    left_at=left_at,
                )
                LocationLog.objects.filter(pk=log.pk).update(
                    created_at=arrived,
                    updated_at=left_at or last_seen,
                )
                created += 1
            except Exception as exc:
                self.stdout.write(self.style.WARNING(
                    f"Konum logu olusturulamadi ({user.email}): {exc}"
                ))
        return created
