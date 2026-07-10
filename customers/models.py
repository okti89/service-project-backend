import uuid

from django.db import models

from core.tenant_context import get_current_tenant


class Customer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.SET_NULL,
        related_name="customers",
        null=True,
        blank=True,
    )
    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    note = models.TextField(blank=True, null=True)
    is_deleted = models.BooleanField(default=False, verbose_name='Silindi')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["full_name"]

    def save(self, *args, **kwargs):
        if not self.tenant_id:
            tenant = get_current_tenant()
            if tenant:
                self.tenant = tenant

        if self.phone_number:
            digits = ''.join(ch for ch in str(self.phone_number) if ch.isdigit())
            if digits:
                if digits.startswith('90') and len(digits) > 10:
                    digits = digits[2:]
                elif digits.startswith('090') and len(digits) > 11:
                    digits = digits[3:]
                
                if not digits.startswith('0') and len(digits) == 10:
                    digits = '0' + digits
                self.phone_number = digits

        super().save(*args, **kwargs)

    def __str__(self):
        return self.full_name
