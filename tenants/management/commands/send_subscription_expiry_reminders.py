from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from accounts.models import User
from notifications.models import Notification
from notifications.services import create_notification
from tenants.models import TenantMembership


class Command(BaseCommand):
    help = 'Sends trial and premium expiry reminders to tenant administrators.'

    def handle(self, *args, **options):
        today = timezone.localdate()
        reminder_dates = [today + timedelta(days=days) for days in (0, 1, 3)]
        latest_membership_id = TenantMembership.objects.filter(
            tenant=OuterRef('tenant')
        ).order_by('-period_number').values('id')[:1]
        memberships = TenantMembership.objects.filter(
            pk=Subquery(latest_membership_id),
            renewal_date__in=reminder_dates,
        ).select_related('tenant').order_by('renewal_date')

        sent_count = 0
        for membership in memberships:
            days_left = (membership.renewal_date - today).days
            plan_label = 'deneme' if membership.plan == TenantMembership.Plan.TRIAL else 'premium'
            if days_left == 0:
                title = 'Firma üyeliğiniz sona erdi'
                message = 'Firma üyeliğiniz bugün sona erdi. Erişimi yeniden açmak için üyeliğinizi yenileyin.'
            else:
                title = f'Firma üyeliğinizin bitmesine {days_left} gün kaldı'
                message = f'{plan_label.title()} üyeliğiniz {membership.renewal_date:%d.%m.%Y} tarihinde sona erecek. Kesintisiz erişim için yenileme planlayın.'

            admins = User.objects.filter(
                tenant=membership.tenant,
                is_active=True,
                approval_status='approved',
            ).filter(is_staff=True) | User.objects.filter(
                tenant=membership.tenant,
                is_active=True,
                approval_status='approved',
                user_type='admin',
            )

            related_id = f'{membership.id}:{days_left}'
            for admin in admins.distinct():
                if Notification.objects.filter(
                    user=admin,
                    related_screen='SubscriptionExpiry',
                    related_id=related_id,
                ).exists():
                    continue
                create_notification(
                    user=admin,
                    title=title,
                    message=message,
                    related_screen='SubscriptionExpiry',
                    related_id=related_id,
                )
                send_mail(title, message, settings.DEFAULT_FROM_EMAIL, [admin.email], fail_silently=False)
                sent_count += 1

        self.stdout.write(self.style.SUCCESS(f'Subscription expiry reminders sent: {sent_count}'))