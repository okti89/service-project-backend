from django.shortcuts import render

# Create your views here.
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from config.models import CompanyConfig
from .models import Account, Transaction, TransactionCategory
from .serializers import AccountSerializer, TransactionCategorySerializer, TransactionSerializer


def _resolve_company_for_user(user):
    tenant = getattr(user, "tenant", None)
    if not tenant:
        return None
    return CompanyConfig.objects.filter(tenant=tenant).order_by("-updated_at").first()


class AccountViewSet(viewsets.ModelViewSet):
    serializer_class = AccountSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Account.objects.filter(tenant=self.request.user.tenant).order_by("name")

    def perform_create(self, serializer):
        serializer.save(
            tenant=self.request.user.tenant,
            company=_resolve_company_for_user(self.request.user),
        )


class TransactionCategoryViewSet(viewsets.ModelViewSet):
    serializer_class = TransactionCategorySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return TransactionCategory.objects.filter(tenant=self.request.user.tenant).order_by("name")

    def perform_create(self, serializer):
        serializer.save(
            tenant=self.request.user.tenant,
            company=_resolve_company_for_user(self.request.user),
        )


class TransactionViewSet(viewsets.ModelViewSet):
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["transaction_type", "account", "category"]
    search_fields = ["description", "receipt_number"]
    ordering_fields = ["date", "amount", "created_at"]
    ordering = ["-date"]

    def get_queryset(self):
        return (
            Transaction.objects.filter(tenant=self.request.user.tenant)
            .select_related("account", "category", "service")
            .order_by("-date")
        )

    def perform_create(self, serializer):
        serializer.save(
            tenant=self.request.user.tenant,
            company=_resolve_company_for_user(self.request.user),
        )

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_retrieved:
            return Response(
                {"detail": "Geri alinan islem guncellenemez."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_retrieved:
            return Response(
                {"detail": "Geri alinan islem guncellenemez."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        return Response(
            {"detail": 'Method "DELETE" not allowed.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=["post"], url_path="reverse")
    def reverse(self, request, pk=None):
        transaction_obj = self.get_object()

        if transaction_obj.is_retrieved:
            return Response(
                {"detail": "Bu islem zaten geri alinmis."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reason = (request.data.get("reason") or "Yanlis islem geri alma").strip()
        note = f"Geri alindi: {reason}"
        current_description = (transaction_obj.description or "").strip()
        transaction_obj.is_retrieved = True
        transaction_obj.description = f"{current_description}\n{note}".strip()
        transaction_obj.save()

        serializer = self.get_serializer(transaction_obj)
        return Response(serializer.data, status=status.HTTP_200_OK)
