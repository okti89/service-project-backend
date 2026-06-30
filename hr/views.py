from django.db import transaction
from django.http import HttpResponse
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.services import create_notification
from technicians.models import Technician

from .models import Payroll, PayrollComponent, PayrollTemplate, TechnicianCompensation
from .permissions import IsHRManager
from .serializers import (
    PayrollComponentSerializer,
    PayrollSerializer,
    PayrollTemplateSerializer,
    TechnicianCompensationSerializer,
)
from .utils import generate_payroll_pdf


class TechnicianMixin:
    def get_technician(self, request):
        return Technician.objects.filter(user=request.user, tenant=request.user.tenant).first()


class TechnicianCompensationViewSet(viewsets.ModelViewSet):
    serializer_class = TechnicianCompensationSerializer
    permission_classes = [IsHRManager]

    def get_queryset(self):
        tenant = getattr(self.request.user, "tenant", None)
        if not tenant:
            return TechnicianCompensation.objects.none()

        return TechnicianCompensation.objects.filter(technician__user__tenant=tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user.tenant)


class PayrollViewSet(viewsets.ModelViewSet):
    serializer_class = PayrollSerializer
    permission_classes = [IsHRManager]
    filterset_fields = ["technician", "period_start", "period_end", "status"]

    def get_queryset(self):
        tenant = getattr(self.request.user, "tenant", None)
        if not tenant:
            return Payroll.objects.none()

        return Payroll.objects.filter(tenant=tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user.tenant)

    @action(detail=True, methods=["post"])
    def send_notification(self, request, pk=None):
        payroll = self.get_object()
        technician_user = payroll.technician.user
        period_text = f"{payroll.period_start:%d.%m.%Y} - {payroll.period_end:%d.%m.%Y}"

        transaction.on_commit(
            lambda: create_notification(
                user=technician_user,
                title="Maas Bordronuz Hazir",
                message=f"{period_text} | Net: {payroll.net_salary} TL",
                related_id=str(payroll.id),
                related_screen="Payroll",
            )
        )

        return Response({"detail": "Bildirim gonderildi"})

    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        payroll = self.get_object()
        pdf_buffer = generate_payroll_pdf(payroll)

        return HttpResponse(
            pdf_buffer,
            content_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="bordro_{payroll.id}.pdf"'
            },
        )

    @action(detail=True, methods=["post"])
    def cancel_payment(self, request, pk=None):
        payroll = self.get_object()

        if payroll.status != "paid":
            return Response({"detail": "Zaten odenmemis."}, status=400)

        payroll.cancel()
        payroll.paid_date = None
        payroll.save(update_fields=["status", "paid_date", "updated_at"])
        payroll.sync_accounting_transaction()

        return Response({"detail": "Odeme iptal edildi"})


class PayrollComponentViewSet(viewsets.ModelViewSet):
    serializer_class = PayrollComponentSerializer
    filterset_fields = ["payroll", "type"]
    permission_classes = [IsHRManager]

    def get_queryset(self):
        tenant = getattr(self.request.user, "tenant", None)
        if not tenant:
            return PayrollComponent.objects.none()

        qs = PayrollComponent.objects.filter(payroll__tenant=tenant)

        # Support bulk fetch: ?payroll_ids=id1,id2,id3
        payroll_ids_param = self.request.query_params.get("payroll_ids", "")
        if payroll_ids_param:
            ids = [pid.strip() for pid in payroll_ids_param.split(",") if pid.strip()]
            if ids:
                qs = qs.filter(payroll_id__in=ids)

        return qs

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user.tenant)


class PayrollTemplateViewSet(viewsets.ModelViewSet):
    serializer_class = PayrollTemplateSerializer
    filterset_fields = ["is_active", "type"]
    permission_classes = [IsHRManager]

    def get_queryset(self):
        tenant = getattr(self.request.user, "tenant", None)
        if not tenant:
            return PayrollTemplate.objects.none()

        return PayrollTemplate.objects.filter(tenant=tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user.tenant)


class TechnicianPayrollListView(APIView, TechnicianMixin):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if request.user.user_type != "technician":
            return Response(
                {"detail": "Bu ekran sadece teknisyen kullanicilar icindir."},
                status=status.HTTP_403_FORBIDDEN,
            )

        technician = self.get_technician(request)
        if not technician:
            return Response(
                {"detail": "Teknisyen bulunamadi"},
                status=status.HTTP_404_NOT_FOUND,
            )

        payrolls = Payroll.objects.filter(
            technician=technician,
            tenant=request.user.tenant,
        ).order_by("-period_start")

        serializer = PayrollSerializer(payrolls, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class TechnicianPayrollPDFView(APIView, TechnicianMixin):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        if request.user.user_type != "technician":
            return Response(
                {"detail": "Bu ekran sadece teknisyen kullanicilar icindir."},
                status=status.HTTP_403_FORBIDDEN,
            )

        technician = self.get_technician(request)
        if not technician:
            return Response(
                {"detail": "Teknisyen profili bulunamadi."},
                status=status.HTTP_404_NOT_FOUND,
            )

        payroll = Payroll.objects.filter(
            pk=pk,
            technician=technician,
            tenant=request.user.tenant,
        ).first()
        if not payroll:
            return Response(
                {"detail": "Bordro bulunamadi."},
                status=status.HTTP_404_NOT_FOUND,
            )

        pdf_buffer = generate_payroll_pdf(payroll)
        filename = f"maas_bordro_{payroll.id}.pdf"

        response = HttpResponse(pdf_buffer, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
