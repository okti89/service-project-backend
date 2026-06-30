"""Tum tenantlar icin HR mock verisi uretir.

Urettikleri:
- PayrollTemplate (tenant basina ekleme/kesinti sablonlari)
- TechnicianCompensation (tenant'daki her teknisyen icin tek seferlik)
- Payroll (son N ay icin her teknisyene bir bordro)
- PayrollComponent (her bordroya ekleme + kesinti)

Ornek:
    python manage.py create_mock_hr --months 3 --seed 42
    python manage.py create_mock_hr --tenant-id <uuid> --wipe
"""

import calendar
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from faker import Faker

from hr.models import (
    Payroll,
    PayrollComponent,
    PayrollTemplate,
    TechnicianCompensation,
)
from technicians.models import Technician
from tenants.models import Tenant


ADDITION_TEMPLATES = [
    ("Yol Yardimi", Decimal("500.00")),
    ("Yemek Yardimi", Decimal("1500.00")),
    ("Performans Primi", Decimal("1000.00")),
    ("Mesai Farki", Decimal("750.00")),
    ("Bayram Bonusu", Decimal("500.00")),
]

DEDUCTION_TEMPLATES = [
    ("SGK Kesintisi", Decimal("300.00")),
    ("Avans Kesintisi", Decimal("250.00")),
    ("Gelir Vergisi", Decimal("450.00")),
    ("Bes Kesintisi", Decimal("200.00")),
    ("Servis Katilim", Decimal("150.00")),
]


class Command(BaseCommand):
    help = "Tum tenantlar icin HR mock verisi (maas sablonlari, ozluk, bordro, kalemler) uretir."

    def add_arguments(self, parser):
        parser.add_argument(
            "--months",
            type=int,
            default=3,
            help="Geriye donuk kac ay icin bordro uretilecegi. Varsayilan: 3",
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
            help="Tenant(lar) icin mevcut HR verilerini once silip yeniden uretir.",
        )

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _month_bounds(reference: date, months_back: int):
        """reference ayinin 1'i referans alinarak geriye dogru aylik (start, end) tuple'larini dondurur."""
        year = reference.year
        month = reference.month - months_back
        while month <= 0:
            month += 12
            year -= 1

        periods = []
        for _ in range(months_back + 1):
            last_day = calendar.monthrange(year, month)[1]
            start = date(year, month, 1)
            end = date(year, month, last_day)
            periods.append((start, end))
            month += 1
            if month > 12:
                month = 1
                year += 1
        return periods

    @staticmethod
    def _random_iban(faker: Faker) -> str:
        digits = "".join(str(random.randint(0, 9)) for _ in range(24))
        return f"TR{digits}"

    # ------------------------------------------------------------------ main

    def handle(self, *args, **options):
        months = options["months"]
        tenant_id = options["tenant_id"]
        seed = options["seed"]
        wipe = options["wipe"]

        if months < 0:
            self.stderr.write(self.style.ERROR("--months 0 veya pozitif olmali."))
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

        today = timezone.localdate()
        periods = self._month_bounds(today, months)

        for tenant in tenants_qs:
            self._process_tenant(
                faker=faker,
                tenant=tenant,
                periods=periods,
                wipe=wipe,
            )

    # ------------------------------------------------------------ per-tenant

    def _process_tenant(self, *, faker: Faker, tenant: Tenant, periods, wipe: bool):
        technicians = list(
            Technician.objects.filter(tenant=tenant).select_related("user")
        )

        if not technicians:
            self.stdout.write(
                self.style.WARNING(
                    f"{tenant.name} ({tenant.id}): teknisyen yok, HR mock verisi atlandi."
                )
            )
            return

        if wipe:
            self._wipe_tenant(tenant)

        with transaction.atomic():
            templates = self._ensure_templates(tenant)

            compensation_count = 0
            payroll_count = 0
            component_count = 0

            for tech in technicians:
                comp = self._ensure_compensation(faker, tenant, tech)
                if comp:
                    compensation_count += 1

                for start, end in periods:
                    payroll, components = self._ensure_payroll(
                        faker=faker,
                        tenant=tenant,
                        technician=tech,
                        period_start=start,
                        period_end=end,
                        templates=templates,
                    )
                    if payroll:
                        payroll_count += 1
                        component_count += components

        self.stdout.write(
            self.style.SUCCESS(
                f"{tenant.name} ({tenant.id}): {compensation_count} ozluk, "
                f"{payroll_count} bordro, {component_count} kalem olusturuldu"
            )
        )

    # ----------------------------------------------------------- per-model

    def _wipe_tenant(self, tenant: Tenant):
        comp_deleted, _ = TechnicianCompensation.objects.filter(
            technician__user__tenant=tenant
        ).delete()
        payroll_deleted, _ = Payroll.objects.filter(tenant=tenant).delete()
        template_deleted, _ = PayrollTemplate.objects.filter(tenant=tenant).delete()

        self.stdout.write(
            self.style.WARNING(
                f"{tenant.name} ({tenant.id}): wipe -> "
                f"{comp_deleted} ozluk, {payroll_deleted} bordro, {template_deleted} sablon silindi"
            )
        )

    def _ensure_templates(self, tenant: Tenant):
        templates = []
        for name, amount in ADDITION_TEMPLATES:
            tpl, _ = PayrollTemplate.objects.get_or_create(
                tenant=tenant,
                name=name,
                type="addition",
                defaults={"default_amount": amount, "is_active": True},
            )
            templates.append(tpl)

        for name, amount in DEDUCTION_TEMPLATES:
            tpl, _ = PayrollTemplate.objects.get_or_create(
                tenant=tenant,
                name=name,
                type="deduction",
                defaults={"default_amount": amount, "is_active": True},
            )
            templates.append(tpl)

        return templates

    def _ensure_compensation(self, faker: Faker, tenant: Tenant, technician: Technician):
        comp = TechnicianCompensation.objects.filter(technician=technician).first()
        if comp:
            return comp

        base = Decimal(random.choice([22000, 25000, 28000, 30000, 32500, 35000, 40000]))
        salary_type = random.choice(["net", "gross"])
        iban = self._random_iban(faker)
        sgk = "".join(str(random.randint(0, 9)) for _ in range(12))

        return TechnicianCompensation.objects.create(
            tenant=tenant,
            technician=technician,
            base_salary=base,
            salary_type=salary_type,
            iban=iban,
            sgk_number=sgk,
        )

    def _ensure_payroll(
        self,
        *,
        faker: Faker,
        tenant: Tenant,
        technician: Technician,
        period_start: date,
        period_end: date,
        templates,
    ):
        payroll = Payroll.objects.filter(
            technician=technician,
            period_start=period_start,
            period_end=period_end,
        ).first()
        if payroll:
            return None, 0

        compensation = getattr(technician, "compensation", None)
        base_salary = compensation.base_salary if compensation else Decimal("0.00")

        is_current = period_end >= timezone.localdate().replace(day=1)
        if is_current:
            status = random.choice(["draft", "draft", "approved"])
        else:
            status = random.choice(["paid", "paid", "paid", "approved"])

        payroll = Payroll.objects.create(
            tenant=tenant,
            technician=technician,
            period_start=period_start,
            period_end=period_end,
            base_salary=base_salary,
            status=status,
            paid_date=(
                timezone.now() - timedelta(days=random.randint(0, 5))
                if status == "paid"
                else None
            ),
        )

        addition_templates = [t for t in templates if t.type == "addition"]
        deduction_templates = [t for t in templates if t.type == "deduction"]

        additions = random.sample(addition_templates, k=random.randint(1, 3))
        deductions = random.sample(deduction_templates, k=random.randint(1, 3))

        created = 0
        for tpl in additions + deductions:
            variation = Decimal(random.randint(-200, 200))
            amount = max(Decimal("0.00"), (tpl.default_amount or Decimal("0.00")) + variation)
            PayrollComponent.objects.create(
                tenant=tenant,
                payroll=payroll,
                name=tpl.name,
                amount=amount,
                type=tpl.type,
                is_manual=False,
            )
            created += 1

        payroll.refresh_from_db()
        return payroll, created