import uuid

from django.db import models


def default_tenant_features():
    return {
        "max_users": 5,
        "has_advanced_reporting": False,
        "storage_limit_gb": 10,
    }


class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    code = models.SlugField(max_length=64, unique=True)
    app_name = models.CharField(max_length=100, null=True, blank=True)
    features = models.JSONField(default=default_tenant_features, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class TenantMembership(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='memberships')
    period_number = models.PositiveIntegerField(editable=False)
    premium_started_at = models.DateField()
    renewal_date = models.DateField(editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-period_number']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'period_number'], name='unique_tenant_membership_period'),
        ]

    @staticmethod
    def one_year_after(value):
        try:
            return value.replace(year=value.year + 1)
        except ValueError:
            return value.replace(year=value.year + 1, month=2, day=28)

    def save(self, *args, **kwargs):
        if not self.period_number:
            last_period = TenantMembership.objects.filter(tenant=self.tenant).order_by('-period_number').values_list('period_number', flat=True).first()
            self.period_number = (last_period or 0) + 1
        if not self.renewal_date:
            self.renewal_date = self.one_year_after(self.premium_started_at)
        super().save(*args, **kwargs)

    def renew(self):
        return TenantMembership.objects.create(tenant=self.tenant, premium_started_at=self.renewal_date)