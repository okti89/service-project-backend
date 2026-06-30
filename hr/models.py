from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
import uuid

class TechnicianCompensation(models.Model):
    SALARY_TYPES = [
        ("net", "Net"),
        ("gross", "Brüt"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='technician_compensations', null=True, blank=True)

    technician = models.OneToOneField(
        "technicians.Technician",
        on_delete=models.CASCADE,
        related_name="compensation"
    )

    base_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    salary_type = models.CharField(max_length=10, choices=SALARY_TYPES, default="net")

    iban = models.CharField(max_length=34, blank=True, null=True)
    sgk_number = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        verbose_name = "Teknisyen Özlük"
        verbose_name_plural = "Teknisyen Özlük Bilgileri"

    def clean(self):
        if self.iban:
            iban = self.iban.replace(" ", "").upper()
            if not iban.startswith("TR") or len(iban) != 26:
                raise ValidationError("Geçersiz IBAN")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return str(self.technician)


class Payroll(models.Model):

    STATUS_CHOICES = [
        ("draft", "Taslak"),
        ("approved", "Onaylandi"),
        ("paid", "Odendi"),
        ("cancelled", "Iptal"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="payrolls",
        null=True,
        blank=True,
    )

    technician = models.ForeignKey(
        "technicians.Technician",
        on_delete=models.CASCADE,
        related_name="payrolls"
    )

    period_start = models.DateField()
    period_end = models.DateField()

    base_salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        editable=False,
        default=0
    )

    total_premiums = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    total_deductions = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    net_salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft"
    )

    paid_date = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_start"]

        constraints = [
            models.UniqueConstraint(
                fields=["technician", "period_start", "period_end"],
                name="unique_payroll_period"
            )
        ]

    def clean(self):
        if self.period_end < self.period_start:
            raise ValidationError(
                "Bitis tarihi baslangic tarihinden küçük olamaz."
            )

    def save(self, *args, **kwargs):

        if not self.base_salary:
            compensation = getattr(
                self.technician,
                "compensation",
                None
            )

            self.base_salary = (
                compensation.base_salary
                if compensation else 0
            )

        self.full_clean()

        super().save(*args, **kwargs)

    def calculate_totals(self):

        additions = self.components.filter(
            type="addition"
        ).aggregate(
            total=Sum("amount")
        )["total"] or 0

        deductions = self.components.filter(
            type="deduction"
        ).aggregate(
            total=Sum("amount")
        )["total"] or 0

        self.total_premiums = additions
        self.total_deductions = deductions

        self.net_salary = (
            self.base_salary + additions
        ) - deductions

    @property
    def is_paid(self):
        return self.status == "paid"

    @is_paid.setter
    def is_paid(self, value):
        if value:
            self.status = "paid"
        elif self.status == "paid":
            self.status = "draft"

    @transaction.atomic
    def mark_as_paid(self):

        payroll = Payroll.objects.select_for_update().get(pk=self.pk)

        if payroll.status == "paid":
            return

        payroll.calculate_totals()

        payroll.status = "paid"
        payroll.paid_date = timezone.now()

        payroll.save()

        payroll.sync_accounting_transaction()

    def transaction_reference(self):
        return f"PAYROLL:{self.pk}"

    def sync_accounting_transaction(self):

        from accounting.models import (
            Transaction,
            TransactionCategory,
            Account,
        )

        tenant = self.tenant

        if not tenant:
            return

        reference = self.transaction_reference()

        # eski transaction geri al
        old_transactions = Transaction.objects.filter(
            tenant=tenant,
            receipt_number=reference,
            is_retrieved=False,
        )

        for tx in old_transactions:
            tx.is_retrieved = True
            tx.save(update_fields=["is_retrieved"])

        if self.status != "paid":
            return

        category, _ = TransactionCategory.objects.get_or_create(
            tenant=tenant,
            name="Maas Gideri",
            defaults={
                "type": "expense"
            }
        )

        account = (
            Account.objects.filter(
                tenant=tenant
            )
            .filter(
                account_type__in=["bank", "cash"]
            )
            .order_by("created_at")
            .first()
        )

        if not account:
            return

        Transaction.objects.create(
            tenant=tenant,
            transaction_type="expense",
            account=account,
            category=category,
            amount=self.net_salary,
            date=self.paid_date or timezone.now(),
            description=f"Maaş - {self.technician}",
            receipt_number=reference,
        )

    def cancel(self):

        if self.status == "cancelled":
            return

        self.status = "cancelled"

        Transaction.objects.filter(
            tenant=self.tenant,
            receipt_number=self.transaction_reference(),
            is_retrieved=False,
        ).update(
            is_retrieved=True
        )

        self.save()

    def __str__(self):
        return (
            f"{self.technician} | "
            f"{self.period_start} - {self.period_end}"
        )


class PayrollComponent(models.Model):

    COMPONENT_TYPES = [
        ("addition", "Eklenti"),
        ("deduction", "Kesinti"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="payroll_components",
        null=True,
        blank=True,
    )

    payroll = models.ForeignKey(
        Payroll,
        related_name="components",
        on_delete=models.CASCADE
    )

    name = models.CharField(max_length=100)

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    type = models.CharField(
        max_length=15,
        choices=COMPONENT_TYPES
    )

    is_manual = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):

        if self.amount < 0:
            raise ValidationError(
                "Tutar negatif olamaz."
            )

    def save(self, *args, **kwargs):

        self.full_clean()

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class PayrollTemplate(models.Model):
    COMPONENT_TYPES = PayrollComponent.COMPONENT_TYPES

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="payroll_templates",
    )
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=15, choices=COMPONENT_TYPES)
    default_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name", "type"],
                name="unique_payroll_template_per_tenant",
            )
        ]

    def __str__(self):
        return self.name


@receiver(post_save, sender=PayrollComponent)
@receiver(post_delete, sender=PayrollComponent)
def update_payroll_totals(sender, instance, **kwargs):

    payroll = instance.payroll

    payroll.calculate_totals()

    Payroll.objects.filter(pk=payroll.pk).update(
        total_premiums=payroll.total_premiums,
        total_deductions=payroll.total_deductions,
        net_salary=payroll.net_salary,
        updated_at=timezone.now(),
    )
