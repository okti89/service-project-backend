import random

from django.core.management.base import BaseCommand
from django.db import transaction
from faker import Faker

from accounts.models import User
from tenants.models import Tenant
from technicians.models import Technician, TechnicianStatus


class Command(BaseCommand):
    help = "Tum tenantlar icin Faker ile belirli sayida mock teknisyen (User + Technician) olusturur."

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=20,
            help="Her tenant icin olusturulacak mock teknisyen sayisi. Varsayilan: 20",
        )
        parser.add_argument(
            "--tenant-id",
            type=str,
            default=None,
            help="Sadece belirli bir tenant icin calistir. Bos birakilirsa tum tenantlar.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=None,
            help="Tekrarlanabilir uretim icin seed degeri.",
        )
        parser.add_argument(
            "--wipe",
            action="store_true",
            help="Tenant(lar)daki mevcut teknisyenleri once sil, sonra mock uret.",
        )
        parser.add_argument(
            "--default-password",
            type=str,
            default="Test1234!",
            help="Olusturulan kullanicilar icin varsayilan parola. Varsayilan: Test1234!",
        )

    def handle(self, *args, **options):
        count = options["count"]
        tenant_id = options["tenant_id"]
        seed = options["seed"]
        wipe = options["wipe"]
        default_password = options["default_password"]

        if count <= 0:
            self.stderr.write(self.style.ERROR("--count pozitif bir tamsayi olmali."))
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

        total_created = 0
        for tenant in tenants_qs:
            if wipe:
                deleted_users, _ = User.objects.filter(
                    tenant=tenant,
                    user_type="technician",
                ).delete()
                self.stdout.write(
                    self.style.WARNING(
                        f"{tenant.name} ({tenant.id}): {deleted_users} mevcut teknisyen kullanicisi silindi"
                    )
                )

            created_for_tenant = self._create_for_tenant(
                faker, tenant, count, default_password
            )
            total_created += created_for_tenant
            self.stdout.write(
                self.style.SUCCESS(
                    f"{tenant.name} ({tenant.id}): {created_for_tenant} mock teknisyen olusturuldu"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Islem tamam. Toplam olusturulan mock teknisyen: {total_created}"
            )
        )
        self.stdout.write(
            self.style.NOTICE(
                f"Varsayilan parola: {default_password}"
            )
        )

    def _create_for_tenant(
        self,
        faker: Faker,
        tenant: Tenant,
        count: int,
        default_password: str,
    ) -> int:
        existing_emails = set(
            User.objects.filter(tenant=tenant)
            .exclude(email__isnull=True)
            .values_list("email", flat=True)
        )
        existing_phones = set(
            User.objects.filter(tenant=tenant)
            .exclude(phone_number__isnull=True)
            .values_list("phone_number", flat=True)
        )

        status = (
            TechnicianStatus.objects.filter(tenant=tenant)
            .order_by("name")
            .first()
        )
        if status is None:
            status = TechnicianStatus.objects.create(
                tenant=tenant,
                name="available",
                color="#28a745",
            )

        created = 0
        attempts = 0
        max_attempts = count * 4

        with transaction.atomic():
            for _ in range(count):
                if attempts >= max_attempts:
                    break
                attempts += 1

                first_name = faker.first_name()
                last_name = faker.last_name()

                email = self._unique_email(
                    faker, first_name, last_name, existing_emails
                )
                if not email:
                    continue
                existing_emails.add(email)

                phone = self._unique_phone(faker, existing_phones)
                if not phone:
                    continue
                existing_phones.add(phone)

                hire_date = faker.date_between(start_date="-3y", end_date="today")

                user = User.objects.create_user(
                    email=email,
                    password=default_password,
                    tenant=tenant,
                    first_name=first_name,
                    last_name=last_name,
                    phone_number=phone,
                    user_type="technician",
                    approval_status="approved",
                    is_active=True,
                    is_staff=False,
                )

                Technician.objects.create(
                    tenant=tenant,
                    user=user,
                    status=status,
                    hire_date=hire_date,
                    is_online=False,
                )
                created += 1

        return created

    @staticmethod
    def _unique_email(faker: Faker, first_name: str, last_name: str, existing: set) -> str | None:
        slug_first = first_name.lower().replace(" ", "").replace("ı", "i").replace("ş", "s").replace("ğ", "g").replace("ü", "u").replace("ö", "o").replace("ç", "c")
        slug_last = last_name.lower().replace(" ", "").replace("ı", "i").replace("ş", "s").replace("ğ", "g").replace("ü", "u").replace("ö", "o").replace("ç", "c")
        candidates = [
            f"{slug_first}.{slug_last}@technician.test",
            f"{slug_first}.{slug_last}@{faker.domain_name()}",
        ]
        for _ in range(20):
            base = faker.email().split("@")[0]
            candidates.append(f"{base}@technician.test")

        for email in candidates:
            if email and email not in existing:
                return email
        return None

    @staticmethod
    def _unique_phone(faker: Faker, existing: set) -> str | None:
        for _ in range(20):
            raw = faker.msisdn()
            digits = "".join(ch for ch in raw if ch.isdigit())
            if not digits:
                continue

            if digits.startswith("00"):
                digits = digits[2:]
            if digits.startswith("90"):
                phone = f"+{digits}"
            elif digits.startswith("0"):
                phone = f"+90{digits[1:]}"
            else:
                phone = f"+90{digits}"

            if phone in existing:
                continue
            if len(phone) < 12 or len(phone) > 16:
                continue
            return phone
        return None
