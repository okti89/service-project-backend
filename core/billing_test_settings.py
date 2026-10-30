import os
os.environ.setdefault('SECRET_KEY', 'local-billing-tests-only')
os.environ.setdefault('DEBUG', 'True')
os.environ.setdefault('EMAIL_HOST_USER', 'test@example.invalid')
os.environ.setdefault('EMAIL_HOST_PASSWORD', 'test-only')
os.environ.setdefault('R2_ENABLED', 'False')
from .settings import *
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
STORAGES = {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
REVENUECAT_SANDBOX_TENANTS = ['billing-demo']
REVENUECAT_ENTITLEMENT_ID = 'company_10'
REVENUECAT_APPLE_PUBLIC_SDK_KEY = 'appl_test_fixture'
REVENUECAT_SECRET_API_KEY = 'sk_server_test_fixture_only'
REVENUECAT_WEBHOOK_AUTHORIZATION = 'Bearer webhook-test-fixture-only'

REVENUECAT_PROJECT_ID = 'projtest'
REVENUECAT_APPLE_APP_ID = 'apptest'
