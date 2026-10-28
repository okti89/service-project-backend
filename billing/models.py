import uuid
from django.db import models
from django.utils import timezone

class AppleBillingAccount(models.Model):
    tenant = models.OneToOneField('tenants.Tenant', on_delete=models.CASCADE, related_name='apple_billing')
    app_account_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

class AppleSubscription(models.Model):
    account = models.ForeignKey(AppleBillingAccount, on_delete=models.CASCADE, related_name='subscriptions')
    original_transaction_id = models.CharField(max_length=128, unique=True)
    transaction_id = models.CharField(max_length=128)
    product_id = models.CharField(max_length=200)
    environment = models.CharField(max_length=20)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    signed_at = models.DateTimeField()
    status = models.PositiveSmallIntegerField()
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_active(self):
        return self.status == 1 and not self.revoked_at and self.expires_at > timezone.now()

class AppleNotification(models.Model):
    notification_id = models.UUIDField(unique=True)
    processed_at = models.DateTimeField(auto_now_add=True)
