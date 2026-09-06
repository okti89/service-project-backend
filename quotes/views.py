from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from services.models import Service, ServiceOperations

from .models import Quote
from .pdf_utils import generate_quote_pdf
from .permissions import IsQuoteManager
from .serializers import QuoteConvertSerializer, QuoteEmailSerializer, QuoteSerializer


class QuoteViewSet(viewsets.ModelViewSet):
    serializer_class = QuoteSerializer
    permission_classes = [IsQuoteManager]

    def get_queryset(self):
        queryset = Quote.objects.filter(tenant=self.request.user.tenant).select_related(
            "customer", "created_by", "converted_service"
        ).prefetch_related("items", "items__product")

        search = str(self.request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(quote_number__icontains=search)
                | Q(customer__full_name__icontains=search)
                | Q(customer__phone_number__icontains=search)
            )

        customer = self.request.query_params.get("customer")
        if customer:
            queryset = queryset.filter(customer_id=customer)
        return queryset

    def perform_create(self, serializer):
        serializer.save(
            tenant=self.request.user.tenant,
            created_by=self.request.user,
        )

    @action(detail=True, methods=["get"], url_path="pdf")
    def pdf(self, request, pk=None):
        quote = self.get_object()
        pdf_buffer = generate_quote_pdf(quote)
        filename = f"Teklif_{quote.quote_number}.pdf"
        response = HttpResponse(pdf_buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @action(detail=True, methods=["post"], url_path="send-email")
    def send_email(self, request, pk=None):
        quote = self.get_object()
        payload = QuoteEmailSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        recipient = payload.validated_data.get("email") or quote.customer.email
        if not recipient:
            return Response(
                {"detail": "Musteri e-posta adresi bulunamadi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        subject = payload.validated_data.get("subject") or f"Fiyat Teklifi {quote.quote_number}"
        message = payload.validated_data.get("message") or "Hazirlanan fiyat teklifi ektedir."
        pdf_buffer = generate_quote_pdf(quote)
        email = EmailMessage(
            subject=subject,
            body=message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            to=[recipient],
        )
        email.attach(
            f"Teklif_{quote.quote_number}.pdf",
            pdf_buffer.getvalue(),
            "application/pdf",
        )
        email.send(fail_silently=False)
        self._mark_sent(quote)
        return Response({"detail": f"Teklif {recipient} adresine gonderildi."})

    @action(detail=True, methods=["post"], url_path="mark-sent")
    def mark_sent(self, request, pk=None):
        quote = self.get_object()
        self._mark_sent(quote)
        return Response({"sent_at": quote.sent_at})

    @action(detail=True, methods=["post"], url_path="convert-to-service")
    def convert_to_service(self, request, pk=None):
        serializer = QuoteConvertSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            quote = get_object_or_404(
                self.get_queryset().select_for_update(),
                pk=pk,
            )
            if quote.converted_service_id:
                return Response(
                    {
                        "detail": "Teklif daha once servise donusturulmus.",
                        "service_id": quote.converted_service_id,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            customer = quote.customer
            service = Service.objects.create(
                tenant=quote.tenant,
                customer=customer,
                customer_full_name=customer.full_name,
                customer_phone=customer.phone_number,
                customer_address=customer.address,
                fault_description=quote.note,
                scheduled_date=serializer.validated_data["scheduled_date"],
                technician=serializer.validated_data.get("technician"),
            )
            for item in quote.items.select_related("product").all():
                ServiceOperations.objects.create(
                    tenant=quote.tenant,
                    service=service,
                    product=item.product,
                    name=item.name,
                    description=item.description,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                )

            quote.converted_service = service
            quote.save(update_fields=["converted_service", "updated_at"])

        return Response(
            {
                "detail": "Teklif servise donusturuldu.",
                "service_id": service.id,
                "receipt_number": service.receipt_number,
            },
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _mark_sent(quote):
        if not quote.sent_at:
            quote.sent_at = timezone.now()
            quote.save(update_fields=["sent_at", "updated_at"])
