import random

from django.core.management.base import BaseCommand
from django.db import transaction
from faker import Faker

from customers.models import Customer
from tenants.models import Tenant


class Command(BaseCommand):
    help = "Tum tenantlar icin Faker ile belirli sayida mock musteri olusturur."

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=50,
            help="Her tenant icin olusturulacak mock musteri sayisi. Varsayilan: 50",
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
            help="Tenant(lar)daki mevcut (silinmemis) musterileri once sil, sonra mock uret.",
        )
        parser.add_argument(
            "--include-deleted",
            action="store_true",
            help="--wipe sirasinda soft-delete edilmis musterileri de dahil et.",
        )

    def handle(self, *args, **options):
        count = options["count"]
        tenant_id = options["tenant_id"]
        seed = options["seed"]
        wipe = options["wipe"]
        include_deleted = options["include_deleted"]

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
                qs = Customer.objects.filter(tenant=tenant)
                if not include_deleted:
                    qs = qs.filter(is_deleted=False)
                deleted, _ = qs.delete()
                self.stdout.write(
                    self.style.WARNING(
                        f"{tenant.name} ({tenant.id}): {deleted} mevcut musteri silindi"
                    )
                )

            created_for_tenant = self._create_for_tenant(faker, tenant, count)
            total_created += created_for_tenant
            self.stdout.write(
                self.style.SUCCESS(
                    f"{tenant.name} ({tenant.id}): {created_for_tenant} mock musteri olusturuldu"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Islem tamam. Toplam olusturulan mock musteri: {total_created}"
            )
        )

    def _create_for_tenant(self, faker: Faker, tenant: Tenant, count: int) -> int:
        existing_phones = set(
            Customer.objects.filter(tenant=tenant)
            .exclude(phone_number__isnull=True)
            .values_list("phone_number", flat=True)
        )

        created = 0
        attempts = 0
        max_attempts = count * 4

        with transaction.atomic():
            customers_to_create = []
            while created < count and attempts < max_attempts:
                attempts += 1

                full_name = faker.name()
                phone = self._unique_phone(faker, existing_phones)
                if not phone:
                    continue
                existing_phones.add(phone)

                email = faker.email() if random.random() > 0.2 else None
                if email:
                    email = email.lower()

                address = faker.address().replace("\n", ", ")
                note = None
                if random.random() > 0.7:
                    note = faker.sentence(nb_words=8)

                customers_to_create.append(
                    Customer(
                        tenant=tenant,
                        full_name=full_name,
                        phone_number=phone,
                        email=email,
                        address=address,
                        note=note,
                        is_deleted=False,
                    )
                )
                created += 1

            Customer.objects.bulk_create(customers_to_create, batch_size=200)

        return created

    @staticmethod
    def _unique_phone(faker: Faker, existing_phones: set) -> str | None:
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

            if phone in existing_phones:
                continue
            if len(phone) < 12 or len(phone) > 16:
                continue
            return phone

        return None
