import random
import string
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, models


class Quote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="quotes",
    )
    quote_number = models.CharField(max_length=20, editable=False)
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="quotes",
    )
    note = models.TextField(blank=True)
    valid_until = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_quotes",
        null=True,
        blank=True,
    )
    converted_service = models.OneToOneField(
        "services.Service",
        on_delete=models.SET_NULL,
        related_name="source_quote",
        null=True,
        blank=True,
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "quote_number"],
                name="uniq_quote_number_per_tenant",
            )
        ]

    @property
    def total_price(self):
        return sum(
            (item.total_price for item in self.items.all()),
            Decimal("0.00"),
        )

    @staticmethod
    def _generate_quote_number():
        suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        return f"TKF-{suffix}"

    def save(self, *args, **kwargs):
        if not self.quote_number:
            for _ in range(8):
                candidate = self._generate_quote_number()
                if not Quote.objects.filter(
                    tenant=self.tenant,
                    quote_number=candidate,
                ).exists():
                    self.quote_number = candidate
                    break
            if not self.quote_number:
                raise IntegrityError("Benzersiz teklif numarasi uretilemedi.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quote_number} - {self.customer}"


class QuoteItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.SET_NULL,
        related_name="quote_items",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255, blank=True)
    description = models.CharField(max_length=255, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="quote_item_quantity_gt_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="quote_item_unit_price_gte_zero",
            ),
        ]

    @property
    def total_price(self):
        return Decimal(self.quantity) * (self.unit_price or Decimal("0.00"))

    def save(self, *args, **kwargs):
        if self.product:
            if not self.name:
                self.name = self.product.name
            if self.unit_price is None:
                self.unit_price = self.product.price or Decimal("0.00")
        if self.unit_price is None:
            self.unit_price = Decimal("0.00")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.quantity} x {self.unit_price})"
