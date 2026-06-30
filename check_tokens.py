import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()

from rest_framework.authtoken.models import Token
from accounts.models import User

print('=== Users ===')
for u in User.objects.all()[:10]:
    print(f' - {u.email} | tenant: {u.tenant} | type: {u.user_type} | active: {u.is_active} | staff: {u.is_staff} | approval: {u.approval_status}')

print()
print('=== Tokens ===')
for t in Token.objects.select_related('user').all()[:10]:
    print(f' - {t.user.email} -> key={t.key[:15]}... (created={t.created})')