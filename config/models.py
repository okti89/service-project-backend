import logging
from django.db import models
from django.core.exceptions import ValidationError
from .utils import process_image
from core.utils import tenant_directory_path
logger = logging.getLogger(__name__)


class CompanyConfig(models.Model):
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='company_configs',
        null=True,
        blank=True
    )

    name = models.CharField(max_length=255, default="Servis Yönetimi")
    panel_url = models.URLField(blank=True, null=True)
    logo = models.ImageField(upload_to=tenant_directory_path, blank=True, null=True)

    phone_number = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    max_users = models.PositiveIntegerField(default=10)

    force_update = models.BooleanField(default=False)
    store_update_url_android = models.URLField(blank=True, null=True)
    store_update_url_ios = models.URLField(blank=True, null=True)
    store_android_version = models.CharField(max_length=20, blank=True, null=True)
    store_ios_version = models.CharField(max_length=20, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Firma Ayarları"
        verbose_name_plural = "Firma Ayarları"
        constraints = [
            models.UniqueConstraint(fields=['tenant'], name='uniq_company_config_tenant'),
        ]

    def save(self, *args, **kwargs):
        is_new = self._state.adding

        # 🔴 FIX: tenant bazlı kontrol daha güvenli
        if is_new and CompanyConfig.objects.filter(tenant=self.tenant).exists():
            raise ValidationError("Sadece bir adet firma yapılandırması oluşturulabilir.")

        # 🔵 IMAGE PROCESS FIX (duplicate kaldırıldı)
        if self.logo:
            try:
                self.logo = process_image(self.logo)
            except Exception:
                logger.exception(
                    "Logo processing failed | company_id=%s tenant_id=%s",
                    self.pk,
                    self.tenant_id
                )

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class WorkingHour(models.Model):
    DAY_CHOICES = [
        (0, 'Pazartesi'),
        (1, 'Salı'),
        (2, 'Çarşamba'),
        (3, 'Perşembe'),
        (4, 'Cuma'),
        (5, 'Cumartesi'),
        (6, 'Pazar'),
    ]
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='working_hour_configs', null=True, blank=True)
    company = models.ForeignKey(CompanyConfig, on_delete=models.CASCADE, related_name='working_hours')
    day_of_week = models.IntegerField(choices=DAY_CHOICES, verbose_name="Gün")
    start_time = models.TimeField(default="08:30", verbose_name="Mesai Başlangıç Saati")
    end_time = models.TimeField(default="18:00", verbose_name="Mesai Bitiş Saati")
    is_holiday = models.BooleanField(default=False, verbose_name="Tatil mi?")

    class Meta:
        verbose_name = "Çalışma Saati"
        verbose_name_plural = "Çalışma Saatleri"
        unique_together = ('company', 'day_of_week')
        ordering = ['day_of_week']

    def __str__(self):
        return f"{self.get_day_of_week_display()} - {self.company.name}"


class HolidayException(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='holiday_exceptions', null=True, blank=True)
    company = models.ForeignKey(CompanyConfig, on_delete=models.CASCADE, related_name='holiday_exceptions')
    title = models.CharField(max_length=120, verbose_name="Açıklama")
    start_date = models.DateField(verbose_name="Başlangıç Tarihi")
    end_date = models.DateField(blank=True, null=True, verbose_name="Bitiş Tarihi")
    is_half_day = models.BooleanField(default=False, verbose_name="Yarım Gün")
    note = models.TextField(blank=True, null=True, verbose_name="Not")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError('Bitiş tarihi başlangıç tarihinden önce olamaz.')
        if self.is_half_day and self.end_date and self.end_date != self.start_date:
            raise ValidationError('Yarım gün seçiliyse bitiş tarihi başlangıç tarihi ile aynı olmalıdır.')

    def __str__(self):
        return f"{self.title} ({self.start_date})"

    class Meta:
        verbose_name = "Tatil İstisnası"
        verbose_name_plural = "Tatil İstisnaları"
        ordering = ['-start_date']



