from rest_framework import permissions, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView
from django.http.request import QueryDict
import ast

from .models import CompanyConfig, WorkingHour, HolidayException
from .serializers import (
    CompanyConfigSerializer,
    WorkingHourSerializer,
    HolidayExceptionSerializer,
)
from .permissions import IsSettingsManager
from tenants.utils import resolve_tenant_from_request


class CompanyConfigViewSet(viewsets.ModelViewSet):
    serializer_class = CompanyConfigSerializer
    permission_classes = [IsSettingsManager]
    queryset = CompanyConfig.objects.none()  # 🔒 tenant safety

    def get_queryset(self):
        return (
            CompanyConfig.objects
            .filter(tenant=self.request.user.tenant)
            .select_related("tenant")
            .prefetch_related("working_hours", "holiday_exceptions")
        )

    def _sanitize_payload(self, data):
        allowed = set(self.get_serializer().fields.keys())
        blocked = {"id", "created_at", "updated_at", "working_hours", "holiday_exceptions"}
        allowed = allowed - blocked

        if isinstance(data, QueryDict):
            payload = QueryDict(mutable=True)
            for key in data.keys():
                if key in allowed:
                    values = data.getlist(key)
                    if len(values) == 1:
                        payload[key] = values[0]
                    else:
                        payload.setlist(key, values)
        else:
            payload = {}
            for key in data.keys():
                if key in allowed:
                    payload[key] = data[key]
        return payload

    def create(self, request, *args, **kwargs):
        # ❗ POST artık sadece create (update hack kaldırıldı)
        payload = self._sanitize_payload(request.data)
        tenant_code = payload.pop("tenant_code", None)

        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        self._update_tenant_code(tenant_code)

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user.tenant)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        payload = self._sanitize_payload(request.data)
        tenant_code = payload.pop("tenant_code", None)

        print(f"[CompanyConfig UPDATE] payload keys: {list(payload.keys())}")
        print(f"[CompanyConfig UPDATE] logo in payload: {'logo' in payload}")
        if 'logo' in payload:
            print(f"[CompanyConfig UPDATE] logo type: {type(payload['logo'])}")

        serializer = self.get_serializer(instance, data=payload, partial=True)
        if not serializer.is_valid():
            print(f"[CompanyConfig UPDATE] serializer errors: {serializer.errors}")
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        self._update_tenant_code(tenant_code)
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)

    def _update_tenant_code(self, tenant_code):
        if not tenant_code:
            return

        tenant = getattr(self.request.user, "tenant", None)
        if not tenant:
            return

        normalized = str(tenant_code).strip()

        # string list fix
        if normalized.startswith("[") and normalized.endswith("]"):
            try:
                parsed = ast.literal_eval(normalized)
                if isinstance(parsed, (list, tuple)) and parsed:
                    normalized = str(parsed[0]).strip()
            except Exception:
                pass

        normalized = normalized.lower()

        if not normalized or tenant.code == normalized:
            return

        # ⚠️ race condition risk reduced (still DB-level constraint önerilir)
        if CompanyConfig.objects.filter(tenant=tenant).exclude(pk=tenant.pk).exists():
            raise ValueError("Bu firma kodu zaten kullanılıyor.")

        tenant.code = normalized
        tenant.save(update_fields=["code", "updated_at"])


class WorkingHourViewSet(viewsets.ModelViewSet):
    serializer_class = WorkingHourSerializer
    permission_classes = [IsSettingsManager]
    queryset = WorkingHour.objects.none()

    def get_queryset(self):
        queryset = (
            WorkingHour.objects
            .filter(company__tenant=self.request.user.tenant)
            .select_related("company")
        )

        company = self.request.query_params.get("company")
        day_of_week = self.request.query_params.get("day_of_week")

        if company:
            queryset = queryset.filter(company_id=company)
        if day_of_week is not None:
            queryset = queryset.filter(day_of_week=day_of_week)

        return queryset


class HolidayExceptionViewSet(viewsets.ModelViewSet):
    serializer_class = HolidayExceptionSerializer
    permission_classes = [IsSettingsManager]
    queryset = HolidayException.objects.none()

    def get_queryset(self):
        queryset = (
            HolidayException.objects
            .filter(company__tenant=self.request.user.tenant)
            .select_related("company")
        )

        company = self.request.query_params.get("company")
        year = self.request.query_params.get("year")
        month = self.request.query_params.get("month")

        if company:
            queryset = queryset.filter(company_id=company)
        if year:
            queryset = queryset.filter(start_date__year=year)
        if month:
            queryset = queryset.filter(start_date__month=month)

        return queryset


class PublicCompanyConfigView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        tenant = resolve_tenant_from_request(request)

        if not tenant:
            return Response(
                {
                    "name": "Servis Yönetim Sistemi",
                    "panel_url": None,
                    "logo": None,
                    "phone_number": None,
                    "email": None,
                    "address": None,
                    "max_users": 0,
                    "working_hours": [],
                    "holiday_exceptions": [],
                },
                status=status.HTTP_200_OK,
            )

        company = (
            CompanyConfig.objects
            .filter(tenant=tenant)
            .select_related("tenant")
            .prefetch_related("working_hours", "holiday_exceptions")
            .first()
        )

        if not company:
            return Response(
                {
                    "name": "Servis Yönetim Sistemi",
                    "panel_url": None,
                    "logo": None,
                    "phone_number": None,
                    "email": None,
                    "address": None,
                    "max_users": 0,
                    "working_hours": [],
                    "holiday_exceptions": [],
                },
                status=status.HTTP_200_OK,
            )

        serializer = CompanyConfigSerializer(company, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)