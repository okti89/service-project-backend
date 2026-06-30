from django.db import models
from django.db.models import F
from django.db.models.signals import post_delete
from django.dispatch import receiver
import uuid
import random

from accounts.models import User
from core.utils import tenant_directory_path
from .utils import process_image


# =========================
# CATEGORY
# =========================
class ProductCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='product_categories',
        null=True,
        blank=True
    )
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


# =========================
# PRODUCT
# =========================
class Product(models.Model):

    STATUS_CHOICES = (
        ('in_stock', 'Stokta Var'),
        ('out_stock', 'Stokta Yok'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='products',
        null=True,
        blank=True
    )

    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        related_name="products"
    )

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True, null=True)

    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    stock_quantity = models.IntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='in_stock')

    image = models.ImageField(upload_to=tenant_directory_path, blank=True, null=True)

    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'code'],
                name='uniq_product_tenant_code'
            )
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    # =========================
    # SAVE OPTIMIZED
    # =========================
    def save(self, *args, **kwargs):

        # STOCK RULE
        if self.stock_quantity is None or self.stock_quantity <= 0:
            self.stock_quantity = 0
            self.status = 'out_stock'
        else:
            self.status = 'in_stock'

        # CODE GENERATION
        if not self.code:
            while True:
                code = f"200{random.randint(1000000000, 9999999999)}"
                if not Product.objects.filter(code=code, tenant=self.tenant).exists():
                    self.code = code
                    break

        # IMAGE PROCESS
        if self.image:
            old_image_name = None
            if self.pk:
                old_image_name = (
                    Product.objects.filter(pk=self.pk)
                    .values_list("image", flat=True)
                    .first()
                )

            if not old_image_name or old_image_name != self.image.name:
                self.image = process_image(self.image)

        super().save(*args, **kwargs)


# =========================
# STOCK MOVEMENT
# =========================
class StockMovement(models.Model):

    MOVEMENT_TYPES = (
        ('in', 'Stok Giriş'),
        ('out', 'Stok Çıkış'),
        ('adjustment', 'Düzeltme'),
        ('return', 'İade'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='stock_movements',
        null=True,
        blank=True
    )

    technician = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="stock_movements"
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="movements"
    )

    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    quantity = models.PositiveIntegerField()
    description = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


    def __str__(self):
        return f"{self.product.name} - {self.movement_type}"


    def save(self, *args, **kwargs):
        is_new = self._state.adding

        super().save(*args, **kwargs)

        if not is_new:
            return

        # STOCK UPDATE SAFE
        if self.movement_type == 'in' or self.movement_type == 'return':
            Product.objects.filter(pk=self.product_id).update(
                stock_quantity=F('stock_quantity') + self.quantity
            )

        elif self.movement_type == 'out':
            Product.objects.filter(pk=self.product_id).update(
                stock_quantity=F('stock_quantity') - self.quantity
            )

        self._fix_stock()


    def _fix_stock(self):
        product = Product.objects.filter(pk=self.product_id).first()
        if not product:
            return

        if product.stock_quantity < 0:
            Product.objects.filter(pk=product.id).update(stock_quantity=0)

        Product.objects.filter(pk=product.id).update(
            status='out_stock' if product.stock_quantity <= 0 else 'in_stock'
        )


# =========================
# DELETE SIGNAL SAFE
# =========================
@receiver(post_delete, sender=StockMovement)
def revert_stock(sender, instance, **kwargs):

    if instance.movement_type in ['in', 'return']:
        Product.objects.filter(pk=instance.product_id).update(
            stock_quantity=F('stock_quantity') - instance.quantity
        )

    elif instance.movement_type == 'out':
        Product.objects.filter(pk=instance.product_id).update(
            stock_quantity=F('stock_quantity') + instance.quantity
        )

    product = Product.objects.filter(pk=instance.product_id).first()

    if product:
        fixed_quantity = max(product.stock_quantity, 0)
        Product.objects.filter(pk=product.id).update(
            stock_quantity=fixed_quantity,
            status='out_stock' if fixed_quantity <= 0 else 'in_stock'
        )
