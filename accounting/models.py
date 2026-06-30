import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone

from core.tenant_context import get_current_tenant


class Account(models.Model):
    ACCOUNT_TYPES = [
        ("cash", "Nakit"),
        ("bank", "Banka Transferi"),
        ("credit_card", "Kredi Karti"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="accounts",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "config.CompanyConfig",
        on_delete=models.CASCADE,
        related_name="accounts",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=100, verbose_name="Hesap Adi")
    account_type = models.CharField(
        max_length=20,
        choices=ACCOUNT_TYPES,
        default="cash",
        verbose_name="Hesap Turu",
    )
    balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Bakiye",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Olusturulma Tarihi")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Guncellenme Tarihi")

    class Meta:
        verbose_name = "Hesap"
        verbose_name_plural = "Hesaplar"

    def clean(self):
        if self.company_id and self.company.tenant_id:
            if self.tenant_id and self.tenant_id != self.company.tenant_id:
                raise ValidationError(
                    {"company": "Hesap firmasi ile tenant bilgisi uyusmuyor."}
                )

    def save(self, *args, **kwargs):
        if not self.tenant_id and self.company_id:
            self.tenant = self.company.tenant

        if not self.tenant_id:
            tenant = get_current_tenant()
            if tenant:
                self.tenant = tenant

        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.balance})"


class TransactionCategory(models.Model):
    TRANSACTION_TYPES = [
        ("income", "Gelir"),
        ("expense", "Gider"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="transaction_categories",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "config.CompanyConfig",
        on_delete=models.CASCADE,
        related_name="transaction_companies",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=100, verbose_name="Kategori Adi")
    type = models.CharField(
        max_length=10,
        choices=TRANSACTION_TYPES,
        verbose_name="Islem Turu",
    )

    class Meta:
        verbose_name = "Islem Kategorisi"
        verbose_name_plural = "Islem Kategorileri"

    def clean(self):
        if self.company_id and self.company.tenant_id:
            if self.tenant_id and self.tenant_id != self.company.tenant_id:
                raise ValidationError(
                    {"company": "Kategori firmasi ile tenant bilgisi uyusmuyor."}
                )

    def save(self, *args, **kwargs):
        if not self.tenant_id and self.company_id:
            self.tenant = self.company.tenant

        if not self.tenant_id:
            tenant = get_current_tenant()
            if tenant:
                self.tenant = tenant

        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"


class Transaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="transactions",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "config.CompanyConfig",
        on_delete=models.CASCADE,
        related_name="transactions",
        null=True,
        blank=True,
    )
    transaction_type = models.CharField(
        max_length=10,
        choices=TransactionCategory.TRANSACTION_TYPES,
        verbose_name="Islem Turu",
    )
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="transactions")
    category = models.ForeignKey(
        TransactionCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateTimeField(default=timezone.now)
    description = models.TextField(blank=True, null=True)
    receipt_number = models.CharField(max_length=50, blank=True, null=True)
    service = models.ForeignKey(
        "services.Service",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_retrieved = models.BooleanField(default=False, verbose_name="Geri Alindi")

    class Meta:
        verbose_name = "Islem"
        verbose_name_plural = "Islemler"
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["account"]),
        ]

    def __str__(self):
        return (
            f"{self.get_transaction_type_display()} - "
            f"({self.date.strftime('%Y-%m-%d')})"
        )

    @staticmethod
    def normalize_receipt_number(receipt_number, max_length=50):
        """
        Servis Odemesi gibi modellerden gelen degerleri receipt_number
        alaninin max_length sinirina gore normalize eder. None veya bos
        degerleri None olarak doner.
        """
        if receipt_number is None:
            return None
        value = str(receipt_number).strip()
        if not value:
            return None
        if len(value) > max_length:
            value = value[:max_length]
        return value

    def _signed_amount(self):
        amount = self.amount or Decimal("0.00")
        return amount if self.transaction_type == "income" else -amount

    def _populate_context_fields(self):
        if self.account_id:
            if not self.tenant_id and self.account.tenant_id:
                self.tenant = self.account.tenant
            if not self.company_id and self.account.company_id:
                self.company = self.account.company

        if self.category_id:
            if not self.tenant_id and self.category.tenant_id:
                self.tenant = self.category.tenant
            if not self.company_id and self.category.company_id:
                self.company = self.category.company

        if self.company_id and not self.tenant_id and self.company.tenant_id:
            self.tenant = self.company.tenant

        if not self.tenant_id:
            tenant = get_current_tenant()
            if tenant:
                self.tenant = tenant

    def clean(self):
        self._populate_context_fields()

        if self.amount is not None and self.amount <= 0:
            raise ValidationError({"amount": "Islem tutari sifirdan buyuk olmali."})

        if self.company_id and self.company.tenant_id:
            if self.tenant_id and self.tenant_id != self.company.tenant_id:
                raise ValidationError(
                    {"company": "Islem firmasi ile tenant bilgisi uyusmuyor."}
                )

        if self.account_id:
            if self.account.tenant_id and self.tenant_id != self.account.tenant_id:
                raise ValidationError(
                    {"account": "Secilen hesap farkli bir tenant'a ait."}
                )
            if self.account.company_id and self.company_id != self.account.company_id:
                raise ValidationError(
                    {"account": "Secilen hesap farkli bir firmaya ait."}
                )

        if self.category_id:
            if self.category.type != self.transaction_type:
                raise ValidationError(
                    {"category": "Kategori tipi islem tipi ile uyusmuyor."}
                )
            if self.category.tenant_id and self.tenant_id != self.category.tenant_id:
                raise ValidationError(
                    {"category": "Secilen kategori farkli bir tenant'a ait."}
                )
            if self.category.company_id and self.company_id != self.category.company_id:
                raise ValidationError(
                    {"category": "Secilen kategori farkli bir firmaya ait."}
                )

    def _balance_adjustments(self, previous):
        adjustments = {}

        if previous and not previous.is_retrieved:
            adjustments[previous.account_id] = (
                adjustments.get(previous.account_id, Decimal("0.00"))
                - previous._signed_amount()
            )

        if not self.is_retrieved:
            adjustments[self.account_id] = (
                adjustments.get(self.account_id, Decimal("0.00"))
                + self._signed_amount()
            )

        return {account_id: delta for account_id, delta in adjustments.items() if delta}

    def save(self, *args, **kwargs):
        self._populate_context_fields()
        self.full_clean()

        with transaction.atomic():
            previous = None
            if self.pk:
                previous = (
                    Transaction.objects.select_for_update()
                    .select_related("account")
                    .filter(pk=self.pk)
                    .first()
                )

            adjustments = self._balance_adjustments(previous)
            account_ids = sorted(adjustments.keys(), key=str)

            if account_ids:
                list(Account.objects.select_for_update().filter(pk__in=account_ids))

            super().save(*args, **kwargs)

            for account_id, delta in adjustments.items():
                Account.objects.filter(pk=account_id).update(
                    balance=F("balance") + delta,
                    updated_at=timezone.now(),
                )
