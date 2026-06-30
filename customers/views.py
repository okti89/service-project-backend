from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Customer
from .serializers import CustomerSerializer


class CustomerListView(generics.ListAPIView):
    """Frontend'in bekledigi '/customer-list/' endpoint'i.

    Aktif/pasif silinmis tum musterileri tenant filtresiyle dondurur.
    """

    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = Customer.objects.filter(
            tenant=self.request.user.tenant,
        ).order_by("full_name")

        status_filter = str(self.request.query_params.get("status", "all")).lower()
        if status_filter in {"active", "all"}:
            queryset = queryset.filter(is_deleted=False)
        elif status_filter == "deleted":
            queryset = queryset.filter(is_deleted=True)

        include_deleted = str(
            self.request.query_params.get("include_deleted", "")
        ).lower() in {"1", "true", "yes"}
        if include_deleted and status_filter == "all":
            pass

        return queryset


class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = Customer.objects.filter(
            tenant=self.request.user.tenant,
        ).order_by("full_name")

        if getattr(self, "action", None) == "restore":
            return queryset

        include_deleted = str(
            self.request.query_params.get("include_deleted", "")
        ).lower() in {"1", "true", "yes"}

        if not include_deleted:
            queryset = queryset.filter(is_deleted=False)

        return queryset

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user.tenant)

    def perform_destroy(self, instance):
        instance.is_deleted = True
        instance.save(update_fields=["is_deleted", "updated_at"])

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        customer = self.get_object()

        if not customer.is_deleted:
            return Response(
                {"detail": "Musteri zaten aktif."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        customer.is_deleted = False
        customer.save(update_fields=["is_deleted", "updated_at"])

        serializer = self.get_serializer(customer)
        return Response(serializer.data, status=status.HTTP_200_OK)
