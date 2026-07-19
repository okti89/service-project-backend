from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from accounts.models import User
from notifications.services import create_notification
from tenants.models import TenantMembership


class Command(BaseCommand):
    help = 'Yaklaşan tenant üyelik yenilemelerini platform yöneticisine bildirir.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30)

    def handle(self, *args, **options):
        days = max(options['days'], 0)
        today = timezone.localdate()
        deadline = today + timedelta(days=days)
        latest_membership_id = TenantMembership.objects.filter(
            tenant=OuterRef('tenant')
        ).order_by('-period_number').values('id')[:1]
        memberships = list(
            TenantMembership.objects.filter(
                pk=Subquery(latest_membership_id),
                renewal_date__range=(today, deadline),
            ).select_related('tenant').order_by('renewal_date')
        )
        recipient = User.objects.filter(is_platform_admin=True, is_active=True).first()
        if not recipient:
            self.stderr.write('Aktif platform yöneticisi bulunamadı; bildirim gönderilmedi.')
            return
        if not memberships:
            self.stdout.write('Yaklaşan üyelik yenilemesi bulunamadı.')
            return
        lines = [
            f'{membership.tenant.name}: {membership.renewal_date:%d.%m.%Y} (Dönem {membership.period_number})'
            for membership in memberships
        ]
        title = f'{len(memberships)} firmanın üyelik yenilemesi yaklaşıyor'
        message = '\n'.join(lines)
        if recipient.tenant_id:
            create_notification(
                recipient,
                title,
                message,
                related_screen='TenantMemberships',
                related_id=today.isoformat(),
            )
        send_mail(title, message, settings.DEFAULT_FROM_EMAIL, [recipient.email], fail_silently=False)
        self.stdout.write(self.style.SUCCESS(f'{len(memberships)} üyelik için bildirim gönderildi.'))