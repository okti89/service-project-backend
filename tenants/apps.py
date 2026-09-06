from django.apps import AppConfig


class TenantsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tenants'
    verbose_name = 'Firmalar ve Üyelikler'

    def ready(self):
        from . import signals  # noqa: F401
