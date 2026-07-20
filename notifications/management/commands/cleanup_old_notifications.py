from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from django.utils import timezone

from notifications.models import Notification
from tenants.models import Tenant


class Command(BaseCommand):
    help = "Tum tenantlardaki belirli bir gun sayisindan eski bildirimleri siler."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=90,
            help="Silinecek bildirimler icin maksimum yas (gun). Varsayilan: 90",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Sadece silinecek kayit sayisini goster, gercek silme yapma.",
        )
        parser.add_argument(
            "--tenant-id",
            type=str,
            default=None,
            help="Sadece belirli bir tenant icin calistir. Bos birakilirsa tum tenantlar.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        dry_run = options["dry_run"]
        tenant_id = options["tenant_id"]

        if days < 0:
            self.stderr.write(self.style.ERROR("--days negatif olamaz."))
            return

        cutoff = timezone.now() - timedelta(days=days)
        self.stdout.write(f"Referans tarihi: {cutoff.isoformat()} ({days} gun once)")

        tenant_filter = Q(notifications__created_at__lt=cutoff)
        tenants_qs = Tenant.objects.all()
        if tenant_id:
            tenants_qs = tenants_qs.filter(id=tenant_id)

        tenants_with_old = (
            tenants_qs.annotate(
                old_count=Count("notifications", filter=tenant_filter),
            )
            .filter(old_count__gt=0)
            .order_by("name")
        )

        total_deleted = 0
        tenant_count = 0
        for tenant in tenants_with_old:
            tenant_count += 1
            old_qs = Notification.objects.filter(
                tenant=tenant, created_at__lt=cutoff
            )
            count = old_qs.count()
            if dry_run:
                self.stdout.write(
                    f"[DRY-RUN] {tenant.name} ({tenant.id}): {count} bildirim silinecek"
                )
            else:
                deleted, _ = old_qs.delete()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{tenant.name} ({tenant.id}): {deleted} bildirim silindi"
                    )
                )
                count = deleted
            total_deleted += count

        if tenant_id:
            scope = f"tenant {tenant_id}"
        else:
            scope = "tum tenantlar"

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"[DRY-RUN] {scope} icin toplam silinecek bildirim: {total_deleted} "
                    f"({tenant_count} tenant)"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{scope} icin toplam silinen bildirim: {total_deleted} "
                    f"({tenant_count} tenant)"
                )
            )
