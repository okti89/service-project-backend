from django.db import models
import uuid
from django.conf import settings
import datetime
from django.db.models import Q
from django.utils import timezone

class TechnicianStatus(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='technician_statuses', null=True, blank=True)
    name = models.CharField(max_length=50)
    color = models.CharField(max_length=20)

    def __str__(self):
        return self.name

class Technician(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='technicians', null=True, blank=True)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, 
        related_name='technician_profile', verbose_name='Teknik Personel')    
    status = models.ForeignKey(TechnicianStatus, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Durum")
    hire_date = models.DateField(default=datetime.date.today, verbose_name="İşe Alım Tarihi")
    is_online = models.BooleanField(default=False, verbose_name="Çevrimiçi")
    last_online = models.DateTimeField(null=True, blank=True, verbose_name="Son Görülme")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Oluşturulma Tarihi")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Güncellenme Tarihi")
    class Meta:
        verbose_name = "Teknisyen Profili"
        verbose_name_plural = "Teknisyen Profilleri"
        
    def __str__(self):
        return f"{self.user.get_full_name()} - Teknisyen"
    
class TechnicianLocation(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='technician_locations', null=True, blank=True)
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='technician_locations')
    location = models.CharField(max_length=255, verbose_name="Konum")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, verbose_name="Enlem")
    longitude = models.DecimalField(max_digits=9, decimal_places=6, verbose_name="Boylam")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Oluşturulma Tarihi")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Güncellenme Tarihi")

    class Meta:
        verbose_name = "Teknisyen Konumu"
        verbose_name_plural = "Teknisyen Konumları"
    
    def __str__(self):
        return f"{self.technician.get_full_name()} - {self.location}"

class TechnicianPermissions(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='technician_permissions', null=True, blank=True)
    technician = models.OneToOneField(
        Technician,
        on_delete=models.CASCADE,
        related_name='permissions',
        verbose_name='Teknisyen'
    )
    
    can_manage_customers = models.BooleanField(default=False, verbose_name="Müşterileri Yönetebilir")
    can_manage_inventory = models.BooleanField(default=False, verbose_name="Envanteri Yönetebilir")
    can_manage_users = models.BooleanField(default=False, verbose_name="Kullanıcıları Yönetebilir")
    can_manage_accounting = models.BooleanField(default=False, verbose_name="Muhasebeyi Yönetebilir")
    can_manage_notifications = models.BooleanField(default=False, verbose_name="Bildirimleri Yönetebilir")
    can_manage_hr = models.BooleanField(default=False, verbose_name="İnsan Kaynaklarını Yönetebilir")
    can_manage_reports = models.BooleanField(default=False, verbose_name="Raporları Yönetebilir")
    can_manage_settings = models.BooleanField(default=False, verbose_name="Ayarları Yönetebilir")
    can_manage_services = models.BooleanField(default=False, verbose_name="Servisleri Yönetebilir")
    can_manage_technicians =models.BooleanField(default=False, verbose_name="Teknisyenleri Yönetebilir")
    can_use_global_search = models.BooleanField(default=False, verbose_name="Global Aramayı Kullanabilir")

    # Permission Flags  
    class Meta:
        verbose_name = "Teknisyen Yetkisi"
        verbose_name_plural = "Teknisyen Yetkileri"

    def __str__(self):
        return f"{self.technician.user.first_name} {self.technician.user.last_name} Yetkileri"

class TechnicianShift(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='technician_shifts', null=True, blank=True)
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='technician_shifts',
        verbose_name="Teknisyen"
    )
    date = models.DateField(default=timezone.now, verbose_name="Tarih")
    start_time = models.DateTimeField(null=True, blank=True,verbose_name="Mesai Başlangıç")
    end_time = models.DateTimeField(null=True, blank=True, verbose_name="Mesai Bitiş")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Oluşturulma Tarihi")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Güncellenme Tarihi")

    class Meta:
        verbose_name = "Teknisyen Mesaisi"
        verbose_name_plural = "Teknisyen Mesaileri"
        ordering = ['-date', '-start_time']

    def __str__(self):
        return f"{self.technician.get_full_name()} - {self.date}"

class TechnicianAttendance(models.Model):
    STATUS_WORKED = "worked"
    STATUS_LEAVE = "leave"
    STATUS_SICK = "sick"
    STATUS_OFFDAY = "offday"
    STATUS_ABSENT = "absent"
    SOURCE_MANUAL = "manual"
    SOURCE_SHIFT = "shift"

    STATUS_CHOICES = [
        (STATUS_WORKED, "Calisti"),
        (STATUS_LEAVE, "Izinli"),
        (STATUS_SICK, "Raporlu"),
        (STATUS_OFFDAY, "Resmi Tatil"),
        (STATUS_ABSENT, "Devamsiz"),
    ]
    SOURCE_CHOICES = [
        (SOURCE_MANUAL, "Manuel"),
        (SOURCE_SHIFT, "Mesai"),
    ]


    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='technician_attendances', null=True, blank=True)
    technician = models.ForeignKey(
        Technician,
        on_delete=models.CASCADE,
        related_name="attendance_records",
        verbose_name="Teknisyen",
    )
    date = models.DateField(default=timezone.now, verbose_name="Tarih")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_WORKED, verbose_name="Durum")
    start_time = models.TimeField(null=True, blank=True, verbose_name="Baslangic Saati")
    end_time = models.TimeField(null=True, blank=True, verbose_name="Bitis Saati")
    note = models.TextField(blank=True, null=True, verbose_name="Not")
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_MANUAL, verbose_name="Kaynak")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Olusturulma Tarihi")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Guncellenme Tarihi")

    class Meta:
        verbose_name = "Teknisyen Devam Durumu"
        verbose_name_plural = "Teknisyen Devam Durumlari"
        ordering = ["-date", "-created_at"]
        unique_together = ("technician", "date")
        indexes = [
            models.Index(fields=["technician", "date"]),
            models.Index(fields=["date"]),
        ]

    def __str__(self):
        return f"{self.technician.user.get_full_name()} - {self.date} - {self.status}"


class LocationLog(models.Model):
    EVENT_ARRIVED = "arrived"
    EVENT_STAYING = "staying"
    EVENT_LEFT = "left"

    EVENT_CHOICES = [
        (EVENT_ARRIVED, "Musteriye Vardi"),
        (EVENT_STAYING, "Musteride Kaliyor"),
        (EVENT_LEFT, "Musteriden Ayrildi"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='location_logs', null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="location_logs",
    )
    technician = models.ForeignKey(
        Technician,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="location_logs",
    )
    service = models.ForeignKey(
        "services.Service",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="location_logs",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="location_logs",
    )
    latitude = models.FloatField()
    longitude = models.FloatField()
    customer_latitude = models.FloatField(null=True, blank=True)
    customer_longitude = models.FloatField(null=True, blank=True)
    last_distance_meters = models.FloatField(null=True, blank=True)
    arrived_at = models.DateTimeField()
    last_seen_at = models.DateTimeField(null=True, blank=True)
    left_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Konum Takip Logu"
        verbose_name_plural = "Konum Takip Loglari"
        ordering = ["-arrived_at"]
        indexes = [
            models.Index(fields=["user", "arrived_at"]),
            models.Index(fields=["service", "arrived_at"]),
            models.Index(fields=["left_at"]),
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.arrived_at}"

