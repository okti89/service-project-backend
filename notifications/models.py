from django.db import models
from django.conf import settings
from django.utils import timezone


class Notification(models.Model):
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='notifications'
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications'
    )

    title = models.CharField(max_length=255)
    message = models.TextField()

    related_id = models.CharField(max_length=255, blank=True, null=True)
    related_screen = models.CharField(max_length=255, blank=True, null=True)
    dedupe_key = models.CharField(max_length=255, blank=True, null=True)

    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'created_at']),
            models.Index(fields=['tenant', 'is_read']),
            models.Index(fields=['user', 'is_read']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'dedupe_key'],
                name='uniq_notification_user_dedupe_key',
            ),
        ]

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])

    def save(self, *args, **kwargs):
        self.tenant = self.user.tenant
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user} - {self.title}"
