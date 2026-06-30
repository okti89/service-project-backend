
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from accounts.models import User
from tenants.models import Tenant

print("=== Tenants ===")
for tenant in Tenant.objects.all():
    print(f"ID: {tenant.id}, Code: {tenant.code}, Name: {tenant.name}, Active: {tenant.is_active}")

print("\n=== Users ===")
for user in User.objects.all():
    print(f"ID: {user.id}, Email: {user.email}, Active: {user.is_active}, User Type: {user.user_type}, Tenant ID: {user.tenant_id}")
