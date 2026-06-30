import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter, SearchFilter

from config.models import CompanyConfig

from .models import Feedback
from .serializers import AdminAppFeedbackSerializer, AppFeedbackSerializer

logger = logging.getLogger(__name__)


class AppFeedbackViewSet(viewsets.ModelViewSet):
    queryset = Feedback.objects.select_related("user").all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["feedback_type", "status"]
    search_fields = ["subject", "message", "user__first_name", "user__last_name"]
    ordering_fields = ["created_at"]

    def get_serializer_class(self):
        user = self.request.user
        if user.is_superuser or getattr(user, "user_type", None) == "admin":
            return AdminAppFeedbackSerializer
        return AppFeedbackSerializer

    def is_admin(self):
        user = self.request.user
        return user.is_superuser or getattr(user, "user_type", None) == "admin"

    def get_queryset(self):
        user = self.request.user
        tenant = getattr(user, "tenant", None)
        qs = super().get_queryset().filter(tenant=tenant)
        if self.is_admin():
            return qs
        return qs.filter(user=user)

    def perform_create(self, serializer):
        feedback = serializer.save(user=self.request.user, tenant=getattr(self.request.user, "tenant", None))

        config = CompanyConfig.objects.filter(tenant=getattr(self.request.user, "tenant", None)).only("name").first()
        company_name = config.name if config else "Bilinmiyor"
        subject = f"Yeni Geri Bildirim: {feedback.get_feedback_type_display()}"
        message = (
            f"Kullanici: {feedback.user.get_full_name()}\n"
            f"Tur: {feedback.get_feedback_type_display()}\n"
            f"Konu: {feedback.subject or '-'}\n"
            f"Mesaj:\n{feedback.message}\n\n"
            f"Sirket: {company_name}"
        )

        def send_email():
            try:
                recipient = getattr(settings, "FEEDBACK_EMAIL", None)
                if not recipient:
                    logger.warning("FEEDBACK_EMAIL tanimli degil")
                    return
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[recipient],
                    fail_silently=False,
                )
            except Exception as exc:
                logger.error("Feedback mail gonderilemedi: %s", exc)

        transaction.on_commit(send_email)
