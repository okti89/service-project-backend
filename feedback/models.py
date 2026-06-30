import uuid

from django.db import models

from accounts.models import User


class Feedback(models.Model):
    FEEDBACK_TYPE_CHOICES = [
        ("bug", "Hata"),
        ("suggestion", "Oneri"),
        ("complaint", "Sikayet"),
        ("other", "Diger"),
    ]
    STATUS_CHOICES = [
        ("new", "Yeni"),
        ("in_progress", "Inceleniyor"),
        ("resolved", "Cozuldu"),
        ("closed", "Kapatildi"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feedbacks",
        verbose_name="Kullanici",
    )
    feedback_type = models.CharField(max_length=20, choices=FEEDBACK_TYPE_CHOICES, default="other", verbose_name="Tur")
    subject = models.CharField(max_length=255, blank=True, null=True, verbose_name="Konu")
    message = models.TextField(verbose_name="Mesaj/Aciklama")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new", verbose_name="Durum")
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="feedbacks",
        verbose_name="Tenant",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Olusturulma Tarihi")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Guncellenme Tarihi")

    class Meta:
        verbose_name = "Geri Bildirim"
        verbose_name_plural = "Geri Bildirimler"
        ordering = ["-created_at"]

    def __str__(self):
        user_display = self.user.get_full_name() if self.user else "Anonim"
        return f"{self.get_feedback_type_display()} - {user_display} ({self.get_status_display()})"
