from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db.models import Count, Q

from .models import Customer
from .serializers import CustomerSerializer


def _search_customers(request):
    queryset = Customer.objects.filter(tenant=request.user.tenant)
    search = str(request.query_params.get('search', '')).strip()
    if search:
        matches = (
            Q(full_name__icontains=search) | Q(phone_number__icontains=search)
            | Q(email__icontains=search) | Q(address__icontains=search) | Q(note__icontains=search)
        )
        phone = CustomerSerializer.normalize_phone(search)
        if phone and all(character.isdigit() or character in '+()- . ' for character in search):
            matches |= Q(phone_number__icontains=phone)
            digits = ''.join(character for character in search if character.isdigit())
            matches |= Q(phone_number__icontains=digits)
        queryset = queryset.filter(matches)
    return queryset


class CustomerPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 100

    def paginate_queryset(self, queryset, request, view=None):
        # Existing mobile callers keep their unpaginated response shape.
        if 'page' not in request.query_params and 'page_size' not in request.query_params:
            return None
        self.summary = _search_customers(request).aggregate(
            total=Count('id'),
            active=Count('id', filter=Q(is_deleted=False)),
            inactive=Count('id', filter=Q(is_deleted=True)),
        )
        return super().paginate_queryset(queryset, request, view)

    def get_paginated_response(self, data):
        return Response({
            'count': self.page.paginator.count,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'results': data,
            'summary': self.summary,
        })


class CustomerListView(generics.ListAPIView):
    """Frontend'in bekledigi '/customer-list/' endpoint'i.

    Aktif/pasif silinmis tum musterileri tenant filtresiyle dondurur.
    """

    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = CustomerPagination

    def get_queryset(self):
        queryset = _search_customers(self.request).order_by('full_name', 'id')

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
    pagination_class = CustomerPagination

    def get_queryset(self):
        queryset = Customer.objects.filter(tenant=self.request.user.tenant).order_by('full_name', 'id')

        if getattr(self, "action", None) == "restore":
            return queryset

        if getattr(self, 'action', None) == 'list':
            queryset = _search_customers(self.request).order_by('full_name', 'id')
            status_filter = self.request.query_params.get('status')
            if status_filter == 'all':
                return queryset
            if status_filter in {'inactive', 'deleted'}:
                return queryset.filter(is_deleted=True)
            if status_filter == 'active':
                return queryset.filter(is_deleted=False)

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
