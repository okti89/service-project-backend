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
