import uuid
from django.db import models
from django.utils import timezone

class BillingAccount(models.Model):
    tenant = models.OneToOneField('tenants.Tenant', on_delete=models.CASCADE, related_name='billing_account')
    app_user_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

class CompanySubscription(models.Model):
    account = models.OneToOneField(BillingAccount, on_delete=models.CASCADE, related_name='subscription')
    product_id = models.CharField(max_length=200)
    environment = models.CharField(max_length=20)
    store = models.CharField(max_length=30, default='app_store')
    expires_at = models.DateTimeField()
    active = models.BooleanField(default=False)
    verified_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_active(self):
        return self.active and self.expires_at > timezone.now()

class BillingEvent(models.Model):
    event_id = models.CharField(max_length=128, unique=True)
    processed_at = models.DateTimeField(auto_now_add=True)
