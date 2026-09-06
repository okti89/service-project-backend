from django.apps import AppConfig


class TechniciansConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'technicians'
    verbose_name = 'Teknisyenler'

    def ready(self):
        from . import signals  # noqa: F401
