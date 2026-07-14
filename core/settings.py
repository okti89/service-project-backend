from pathlib import Path
import os
from urllib.parse import unquote, urlparse
from decouple import config
from django.core.exceptions import ImproperlyConfigured
from corsheaders.defaults import default_headers

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=False, cast=bool)

def env_list(name, default=''):
    return [value.strip() for value in config(name, default=default).split(',') if value.strip()]


ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', '*' if DEBUG else '')
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured('ALLOWED_HOSTS must be set when DEBUG=False.')

# Application definition
AUTH_USER_MODEL = 'accounts.User'
CORS_ALLOW_ALL_ORIGINS = config('CORS_ALLOW_ALL_ORIGINS', default=DEBUG, cast=bool)
CORS_ALLOWED_ORIGINS = env_list('CORS_ALLOWED_ORIGINS')
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS')

CORS_ALLOWED_ORIGINS = os.getenv('CORS_ALLOWED_ORIGINS', 'https://servis-yonetim.onrender.com,https://imrpx8h1iihplrf4rs1ssbqo.5.75.152.139.sslip.io,http://localhost:3000').split(',')
CORS_ALLOW_CREDENTIALS = True # Bu ayar TRUE kalmalı
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'x-tenant-code',
]

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'import_export',
    'rest_framework',
    'corsheaders',
    'django_cleanup.apps.CleanupConfig',
    'rest_framework.authtoken',
    'django_filters',
    'storages',

    'accounting',
    'accounts',
    'config',
    'customers',
    'technicians.apps.TechniciansConfig',
    'services',
    'notifications',
    #'planners',
    'products',
    'hr',
    'reports',
    'feedback',
    'tenants',
    'maps',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.tenant_middleware.TenantContextMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'


REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',

    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
        # 'core.permissions.IsDemoRestricted',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
    ]
}

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default=EMAIL_HOST_USER)

FEEDBACK_EMAIL = "teknoktay@gmail.com"


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

def database_config_from_url(database_url):
    parsed = urlparse(database_url)
    if parsed.scheme not in ('postgres', 'postgresql'):
        raise ImproperlyConfigured('DATABASE_URL must use the postgresql scheme.')

    database_name = unquote(parsed.path.lstrip('/'))
    if not database_name:
        raise ImproperlyConfigured('DATABASE_URL must include a database name.')

    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': database_name,
        'USER': unquote(parsed.username or ''),
        'PASSWORD': unquote(parsed.password or ''),
        'HOST': parsed.hostname or '',
        'PORT': str(parsed.port or ''),
        'CONN_MAX_AGE': 600,
        'CONN_HEALTH_CHECKS': True,
    }


DATABASE_URL = config('DATABASE_URL', default='')
if DATABASE_URL:
    DATABASES = {'default': database_config_from_url(DATABASE_URL)}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

if not DEBUG and not DATABASE_URL:
    raise ImproperlyConfigured('DATABASE_URL must be set when DEBUG=False.')


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'tr'

TIME_ZONE = 'Europe/Istanbul'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = '/static/'
# Static assets are rebuilt on each deploy, so keep them outside application and media mounts.
STATIC_ROOT = config('STATIC_ROOT', default=str(BASE_DIR / 'staticfiles') if DEBUG else '/tmp/service-staticfiles')
STATICFILES_STORAGE_BACKEND = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=not DEBUG, cast=bool)
SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=not DEBUG, cast=bool)
CSRF_COOKIE_SECURE = config('CSRF_COOKIE_SECURE', default=not DEBUG, cast=bool)
SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=31536000 if not DEBUG else 0, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False, cast=bool)
SECURE_HSTS_PRELOAD = config('SECURE_HSTS_PRELOAD', default=False, cast=bool)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

# Cloudflare R2 (S3 compatible) settings
R2_ENABLED = config('R2_ENABLED', default=True, cast=bool)
R2_ACCOUNT_ID = config('R2_ACCOUNT_ID', default='')
R2_ENDPOINT_URL = config('R2_ENDPOINT_URL', default='')
R2_BUCKET_NAME = config('R2_BUCKET_NAME', default='')
R2_ACCESS_KEY_ID = config('R2_ACCESS_KEY_ID', default='')
R2_SECRET_ACCESS_KEY = config('R2_SECRET_ACCESS_KEY', default='')
R2_CUSTOM_DOMAIN = config('R2_CUSTOM_DOMAIN', default='').strip().strip('"').strip("'")

if not R2_ENDPOINT_URL and R2_ACCOUNT_ID:
    R2_ENDPOINT_URL = f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com'

R2_IS_CONFIGURED = R2_ENABLED and all(
    [R2_ENDPOINT_URL, R2_BUCKET_NAME, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY]
)
SERVE_MEDIA_WITH_DJANGO = config(
    'SERVE_MEDIA_WITH_DJANGO',
    default=not R2_IS_CONFIGURED,
    cast=bool,
)

if R2_IS_CONFIGURED:
    AWS_ACCESS_KEY_ID = R2_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY = R2_SECRET_ACCESS_KEY
    AWS_STORAGE_BUCKET_NAME = R2_BUCKET_NAME
    AWS_S3_ENDPOINT_URL = R2_ENDPOINT_URL
    AWS_S3_REGION_NAME = 'auto'
    AWS_S3_SIGNATURE_VERSION = 's3v4'
    AWS_S3_ADDRESSING_STYLE = 'path'
    AWS_DEFAULT_ACL = None
    AWS_S3_FILE_OVERWRITE = False
    AWS_QUERYSTRING_AUTH = True
    AWS_S3_OBJECT_PARAMETERS = {
        'CacheControl': 'max-age=86400',
    }

    # Accept both:
    # - R2_CUSTOM_DOMAIN=pub-xxxx.r2.dev
    # - R2_CUSTOM_DOMAIN=https://pub-xxxx.r2.dev
    if R2_CUSTOM_DOMAIN:
        parsed_domain = urlparse(R2_CUSTOM_DOMAIN)
        AWS_S3_CUSTOM_DOMAIN = parsed_domain.netloc or parsed_domain.path
    else:
        AWS_S3_CUSTOM_DOMAIN = ''

    STORAGES = {
        'default': {
            'BACKEND': 'storages.backends.s3.S3Storage',
        },
        'staticfiles': {
            'BACKEND': STATICFILES_STORAGE_BACKEND,
        },
    }

    if AWS_S3_CUSTOM_DOMAIN:
        MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/'
    else:
        # Fallback URL works for API-style access, but for browser public access
        # you should use R2_CUSTOM_DOMAIN (r2.dev or your own custom domain).
        MEDIA_URL = f'{AWS_S3_ENDPOINT_URL}/{AWS_STORAGE_BUCKET_NAME}/'

    # Keep MEDIA_ROOT defined for compatibility even when remote storage is active.
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
else:
    STORAGES = {
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': STATICFILES_STORAGE_BACKEND,
        },
    }
    MEDIA_URL = '/media/'
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')




# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------------------------------------------------------------------------
# Harita / Maps API anahtarlari
# ---------------------------------------------------------------------------
# GOOGLE_MAPS_KEY: Google Maps Platform anahtari (directions + geocoding icin).
# Verilmezse Photon (geocode) ve OSRM (directions) ucretsiz fallback'leri
# kullanilir. Key aktif olunca otomatik olarak Google'a gecis yapilir.
#
# .env dosyasinda tanimlamak yeterlidir:
#   GOOGLE_MAPS_KEY=AIzaSy...
GOOGLE_MAPS_KEY = config('GOOGLE_MAPS_KEY', default='')

# Tenant basina aylik harita istek limiti. Override etmek icin
# MAPS_MONTHLY_QUOTA env degiskeni kullanilabilir.
MAPS_MONTHLY_QUOTA = config('MAPS_MONTHLY_QUOTA', default=1000, cast=int)
