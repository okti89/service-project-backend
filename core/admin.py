from django.contrib import admin
from django.core.exceptions import FieldDoesNotExist


admin.site.site_header = "Servis Yönetimi"
admin.site.site_title = "Servis Yönetimi"
admin.site.index_title = "Yönetim Paneli"
admin.site.empty_value_display = "-"


class TurkishAdminMixin:
    """Admin etiketlerini model şemasını değiştirmeden Türkçeleştirir."""

    admin_verbose_name = None
    admin_verbose_name_plural = None
    admin_field_labels = {}
    list_per_page = 50
    save_on_top = True

    def __init__(self, model, admin_site):
        if self.admin_verbose_name:
            model._meta.verbose_name = self.admin_verbose_name
        if self.admin_verbose_name_plural:
            model._meta.verbose_name_plural = self.admin_verbose_name_plural

        for field_name, label in self.admin_field_labels.items():
            try:
                model._meta.get_field(field_name).verbose_name = label
            except FieldDoesNotExist:
                continue

        super().__init__(model, admin_site)
