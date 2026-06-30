from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from .models import CompanyConfig, WorkingHour


@receiver(post_save, sender=CompanyConfig)
def create_default_working_hours(sender, instance, created, **kwargs):
    """
    CompanyConfig ilk oluşturulduğunda default çalışma saatlerini oluşturur.
    """
    if not created:
        return

    default_hours = [
        (0, "08:30", "18:00"),  # Pazartesi
        (1, "08:30", "18:00"),  # Salı
        (2, "08:30", "18:00"),  # Çarşamba
        (3, "08:30", "18:00"),  # Perşembe
        (4, "08:30", "18:00"),  # Cuma
        (5, "00:00", "00:00"),  # Cumartesi
        (6, "00:00", "00:00"),  # Pazar
    ]

    working_hours = [
        WorkingHour(
            company=instance,
            day_of_week=day,
            start_time=start,
            end_time=end,
            is_holiday=(day >= 5),
        )
        for day, start, end in default_hours
    ]

    WorkingHour.objects.bulk_create(working_hours)



# ----------------------------
# 1. Singleton guard (extra güvenlik)
# ----------------------------
@receiver(pre_save, sender=CompanyConfig)
def ensure_single_company_config(sender, instance, **kwargs):
    if not instance.pk:
        exists = CompanyConfig.objects.filter(tenant=instance.tenant).exists()
        if exists:
            raise ValidationError("Sadece bir adet firma yapılandırması oluşturulabilir.")


# ----------------------------
# 2. WorkingHour otomatik fix (duplicate / eksik gün engelleme)
# ----------------------------
@receiver(post_save, sender=CompanyConfig)
def create_default_working_hours(sender, instance, created, **kwargs):
    if not created:
        return

    existing_days = set(
        WorkingHour.objects.filter(company=instance).values_list("day_of_week", flat=True)
    )

    default_hours = []

    for day in range(7):
        if day in existing_days:
            continue

        is_weekend = day >= 5

        default_hours.append(
            WorkingHour(
                company=instance,
                day_of_week=day,
                start_time="08:30" if not is_weekend else "00:00",
                end_time="18:00" if not is_weekend else "00:00",
                is_holiday=is_weekend,
            )
        )

    if default_hours:
        WorkingHour.objects.bulk_create(default_hours)