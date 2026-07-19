import uuid
import secrets
from datetime import timedelta
from accounts.utils import process_image

from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager

from core.tenant_context import get_current_tenant
from core.utils import tenant_directory_path

class CustomUserManager(BaseUserManager):

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email zorunludur")

        email = self.normalize_email(email)

        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)

        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("user_type", "admin")
        extra_fields.setdefault("approval_status", "approved")

        return self.create_user(email, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="users",
        null=True,
        blank=True
    )

    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=15, unique=True, null=True, blank=True)

    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)

    avatar = models.ImageField(upload_to=tenant_directory_path, blank=True, null=True)

    password_reset_code = models.CharField(max_length=4, null=True, blank=True)
    password_reset_code_sent_at = models.DateTimeField(null=True, blank=True)

    APPROVAL_STATUS_CHOICES = [
        ("pending", "Onay Bekliyor"),
        ("approved", "Onaylandı"),
        ("rejected", "Reddedildi"),
    ]

    approval_status = models.CharField(
        max_length=20,
        choices=APPROVAL_STATUS_CHOICES,
        default="pending"
    )

    USER_TYPE_CHOICES = [
        ("admin", "Yönetici"),
        ("technician", "Teknisyen"),
    ]

    user_type = models.CharField(
        max_length=20,
        choices=USER_TYPE_CHOICES,
        default="technician"
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_platform_admin = models.BooleanField(default=False)

    date_joined = models.DateTimeField(default=timezone.now)

    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "phone_number"],
                name="uniq_user_tenant_phone"
            ),
            models.UniqueConstraint(
                fields=['is_platform_admin'],
                condition=Q(is_platform_admin=True),
                name='single_platform_admin_user',
            ),
        ]

    def __str__(self):
        return self.email

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email

    def get_short_name(self):
        return self.first_name or self.email

    @property
    def password_reset_code_expired(self):
        if not self.password_reset_code_sent_at:
            return False

        expiration_time = self.password_reset_code_sent_at + timedelta(
            hours=getattr(settings, "VERIFICATION_CODE_EXPIRY_HOURS", 24)
        )

        return timezone.now() > expiration_time

    def generate_password_reset_code(self):
        code = f"{secrets.randbelow(10000):04d}"

        self.password_reset_code = code
        self.password_reset_code_sent_at = timezone.now()

        self.save(update_fields=[
            "password_reset_code",
            "password_reset_code_sent_at"
        ])

        return code

    def save(self, *args, **kwargs):

        # tenant auto set (minimal bırakıldı)
        if not self.tenant_id:
            tenant = get_current_tenant()
            if tenant:
                self.tenant = tenant

        # avatar processing (sadece değiştiyse)
        if self.pk:
            try:
                old = User.objects.get(pk=self.pk)

                if self.avatar and old.avatar != self.avatar:
                    self.avatar = process_image(self.avatar)

            except User.DoesNotExist:
                if self.avatar:
                    self.avatar = process_image(self.avatar)
        else:
            if self.avatar:
                self.avatar = process_image(self.avatar)

        super().save(*args, **kwargs)



class UserDevice(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='user_devices', null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_device"
    )

    device_id = models.CharField(max_length=255, blank=True, null=True)
    device_name = models.CharField(max_length=255, blank=True, null=True)

    platform = models.CharField(
        max_length=20,
        choices=[
            ("ios", "iOS"),
            ("android", "Android"),
            ("web", "Web")
        ],
        default="android"
    )
    expo_token = models.CharField(max_length=255, unique=True)
    location_permission = models.BooleanField(default=False)
    notification_permission = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.tenant_id and getattr(self.user, "tenant_id", None):
            self.tenant = self.user.tenant
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.device_name}"


class AccountDeletionRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_COMPLETED = "completed"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "İnceleme Bekliyor"),
        (STATUS_COMPLETED, "Tamamlandı"),
        (STATUS_REJECTED, "Reddedildi"),
    ]

    email = models.EmailField(db_index=True)
    note = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Hesap Silme Talebi"
        verbose_name_plural = "Hesap Silme Talepleri"

    def __str__(self):
        return f"{self.email} - {self.get_status_display()}"