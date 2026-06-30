import datetime
import math
import logging
from typing import Optional

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q
from django.db.models import BooleanField, Case, Value, When
from accounts.serializers import UserCreateSerializer
from services.models import Service
from notifications.services import create_bulk_notification, create_notification
from accounts.models import User
from .models import (
    LocationLog,
    Technician,
    TechnicianAttendance,
    TechnicianLocation,
    TechnicianPermissions,
    TechnicianShift,
    TechnicianStatus,
)

from .serializers import (
    LocationLogSerializer,
    TechnicianAttendanceSerializer,
    TechnicianListSerializer,
    TechnicianLocationSerializer,
    TechnicianShiftSerializer,
    TechnicianStatusSerializer,
    TechnicianPermissionsSerializer
)

TECHNICIAN_PERMISSION_FIELDS = [
    "can_manage_customers",
    "can_manage_inventory",
    "can_manage_users",
    "can_manage_accounting",
    "can_manage_notifications",
    "can_manage_hr",
    "can_manage_reports",
    "can_manage_settings",
    "can_manage_services",
    "can_use_global_search",
    "can_manage_technicians"
]

STATUS_META = {
    "Müsait": "#28a745",
    "İzinli": "#ffc107",
}
ARRIVAL_RADIUS_METERS_DEFAULT = 120.0
STAYING_EVENT_INTERVAL_SECONDS = 120
logger = logging.getLogger(__name__)

def _request_tenant(request):
    return getattr(getattr(request, "user", None), "tenant", None)


def _technician_queryset(request):
    tenant = _request_tenant(request)
    if tenant:
        return Technician.objects.filter(tenant=tenant)
    return Technician.objects.none()

def parse_iso_date(value: str) -> Optional[datetime.date]:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def parse_iso_time(value: str) -> Optional[datetime.time]:
    if not value:
        return None
    try:
        return datetime.time.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def parse_iso_datetime(value: str) -> Optional[datetime.datetime]:
    if not value:
        return None

    parsed = parse_datetime(value)
    if not parsed:
        return None

    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def local_date_from_datetime(value: Optional[datetime.datetime]) -> datetime.date:
    if not value:
        return timezone.localdate()
    return timezone.localtime(value).date()


def resolve_shift_status(shift: TechnicianShift) -> str:
    if shift.end_time:
        return "completed"
    return "in_progress"


def build_shift_payload(shift: TechnicianShift, technician: Technician):
    data = TechnicianShiftSerializer(shift).data
    data["shift_status"] = resolve_shift_status(shift)
    data["technician_profile_id"] = str(technician.id)
    data["technician_name"] = technician.user.get_full_name()
    return data


def month_date_range(month_str: str):
    if not month_str or len(month_str) != 7:
        return None, None

    try:
        year = int(month_str[:4])
        month = int(month_str[5:7])
        first = datetime.date(year, month, 1)
    except (TypeError, ValueError):
        return None, None

    if month == 12:
        last = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        last = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

    return first, last


def resolve_status(status_code: Optional[str], tenant=None) -> TechnicianStatus:
    code = (status_code or "available").strip().lower()
    color = STATUS_META.get(code, "#6c757d")
    status_qs = TechnicianStatus.objects.all()
    if tenant:
        status_qs = status_qs.filter(tenant=tenant)

    obj = status_qs.filter(name=code).first()
    created = False
    if not obj:
        obj, created = TechnicianStatus.objects.get_or_create(
        name=code,
        tenant=tenant,
        defaults={"color": color},
        )

    if not created and not obj.color:
        obj.color = color
        obj.save(update_fields=["color"])

    return obj


def normalize_permission_payload(payload):
    payload = payload or {}
    return {field: bool(payload.get(field, False)) for field in TECHNICIAN_PERMISSION_FIELDS}


def combine_aware(dt_date: datetime.date, dt_time: datetime.time):
    naive = datetime.datetime.combine(dt_date, dt_time)
    if timezone.is_naive(naive):
        return timezone.make_aware(naive, timezone.get_current_timezone())
    return naive


def haversine_distance_meters(lat1, lon1, lat2, lon2):
    earth_radius = 6371000

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return earth_radius * c


def sync_shift_from_attendance(attendance: TechnicianAttendance):
    if attendance.status == TechnicianAttendance.STATUS_WORKED:
        shift, _ = TechnicianShift.objects.get_or_create(
            technician=attendance.technician.user,
            date=attendance.date,
        )

        start_time = attendance.start_time or datetime.time(hour=9, minute=0)
        end_time = attendance.end_time

        updates = {
            "start_time": combine_aware(attendance.date, start_time),
            "end_time": combine_aware(attendance.date, end_time) if end_time else None,
        }
        TechnicianShift.objects.filter(pk=shift.pk).update(**updates)
    else:
        TechnicianShift.objects.filter(
            technician=attendance.technician.user,
            date=attendance.date,
        ).delete()



class TechnicianListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        include_inactive = request.query_params.get("include_inactive", "true").lower() == "true"

        queryset = _technician_queryset(request).select_related("user", "status").prefetch_related("permissions")
        queryset = queryset.filter(user__user_type__in=["technician", "admin"])
        queryset = queryset.annotate(
            is_self=Case(
                When(user_id=request.user.id, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            )
        )

        if not include_inactive:
            queryset = queryset.filter(user__is_active=True)

        serializer = TechnicianListSerializer(
            queryset.order_by("user__first_name", "user__last_name"),
            many=True,
            context={"request": request},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        user_data = request.data.get("user_data") or {}
        if not isinstance(user_data, dict):
            return Response({"detail": "user_data nesnesi zorunludur."}, status=status.HTTP_400_BAD_REQUEST)

        payload = {
            "first_name": user_data.get("first_name", ""),
            "last_name": user_data.get("last_name", ""),
            "email": user_data.get("email"),
            "phone_number": user_data.get("phone_number"),
            "password": user_data.get("password"),
            "user_type": "technician",
        }

        serializer = UserCreateSerializer(data=payload, context={"request": request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        hire_date = parse_iso_date(request.data.get("hire_date")) or timezone.localdate()
        status_obj = resolve_status(request.data.get("status"), tenant=_request_tenant(request))
        permissions_payload = normalize_permission_payload(request.data.get("permissions"))

        with transaction.atomic():
            user = serializer.save()
            user.approval_status = "approved"
            user.is_active = True
            user.user_type = "technician"
            user.save(update_fields=["approval_status", "is_active", "user_type"])

            technician = Technician.objects.create(
                user=user,
                hire_date=hire_date,
                status=status_obj,
            )

            TechnicianPermissions.objects.update_or_create(
                technician=technician,
                defaults=permissions_payload,
            )

        output = TechnicianListSerializer(technician, context={"request": request})
        return Response(output.data, status=status.HTTP_201_CREATED)

class TechnicianDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, technician_id):
        technician = get_object_or_404(
            _technician_queryset(request).select_related("user", "status").prefetch_related("permissions"),
            id=technician_id,
        )
        technician.is_self = technician.user_id == request.user.id
        serializer = TechnicianListSerializer(technician, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, technician_id):
        technician = get_object_or_404(
            _technician_queryset(request).select_related("user", "status").prefetch_related("permissions"),
            id=technician_id,
        )

        user = technician.user
        user_fields = ["first_name", "last_name", "email", "phone_number"]
        changed_user_fields = []
        for field in user_fields:
            if field in request.data:
                setattr(user, field, request.data.get(field))
                changed_user_fields.append(field)

        if changed_user_fields:
            user.save(update_fields=changed_user_fields)

        update_fields = []
        if "hire_date" in request.data:
            parsed_date = parse_iso_date(request.data.get("hire_date"))
            if not parsed_date:
                return Response({"hire_date": ["Gecerli tarih formati girin (YYYY-MM-DD)."]}, status=status.HTTP_400_BAD_REQUEST)
            technician.hire_date = parsed_date
            update_fields.append("hire_date")

        if "status" in request.data:
            technician.status = resolve_status(request.data.get("status"), tenant=_request_tenant(request))
            update_fields.append("status")

        if update_fields:
            technician.save(update_fields=update_fields)

        output = TechnicianListSerializer(technician, context={"request": request})
        return Response(output.data, status=status.HTTP_200_OK)

    def delete(self, request, technician_id):
        technician = get_object_or_404(_technician_queryset(request), id=technician_id)
        user = technician.user
        user.is_active = False
        user.save(update_fields=["is_active"])
        return Response({"detail": "Teknisyen pasife alindi."}, status=status.HTTP_200_OK)

class TechnicianRestoreView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, technician_id):
        technician = get_object_or_404(_technician_queryset(request), id=technician_id)
        user = technician.user
        user.is_active = True
        user.approval_status = "approved"
        user.save(update_fields=["is_active", "approval_status"])
        return Response({"detail": "Teknisyen tekrar aktif edildi."}, status=status.HTTP_200_OK)

class TechnicianPermissionsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, technician_id):
        technician = get_object_or_404(_technician_queryset(request), id=technician_id)
        permission_obj, _ = TechnicianPermissions.objects.get_or_create(technician=technician)
        serializer = TechnicianPermissionsSerializer(permission_obj)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, technician_id):
        technician = get_object_or_404(_technician_queryset(request), id=technician_id)
        permission_obj, _ = TechnicianPermissions.objects.get_or_create(technician=technician)
        serializer = TechnicianPermissionsSerializer(permission_obj, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


class TechnicianStatusListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        tenant = _request_tenant(request)
        existing = TechnicianStatus.objects.filter(tenant=tenant).exists()
        if not existing:
            for code, color in STATUS_META.items():
                TechnicianStatus.objects.create(
                    name=code,
                    tenant=tenant,
                    color=color,
                )
        statuses = TechnicianStatus.objects.filter(tenant=tenant).distinct()
        serializer = TechnicianStatusSerializer(statuses, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

#buna gerek olmayailbilir sonra karar ver
class TechnicianMeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        technician = Technician.objects.select_related("user", "status").prefetch_related("permissions").filter(
            user=request.user,
            user__tenant=_request_tenant(request),
        ).first()
        if not technician:
            return Response({"detail": "Teknisyen profili bulunamadi."}, status=status.HTTP_404_NOT_FOUND)

        serializer = TechnicianListSerializer(technician, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

class TechnicianLocationsByTechnicianView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, technician_id):
        technician = get_object_or_404(_technician_queryset(request), id=technician_id)
        queryset = TechnicianLocation.objects.filter(technician=technician.user).order_by("created_at")
        
        date_str = request.query_params.get("date")
        if date_str:
            parsed_date = parse_iso_date(date_str)
            if parsed_date:
                queryset = queryset.filter(created_at__date=parsed_date)
                
        serializer = TechnicianLocationSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class TechnicianLocationPingView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        technician = Technician.objects.filter(user=request.user, user__tenant=_request_tenant(request)).first()
        if not technician:
            return Response(
                {"detail": "Teknisyen profili bulunamadi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        latitude = request.data.get("latitude")
        longitude = request.data.get("longitude")
        location_text = request.data.get("location") or ""

        if latitude is None or longitude is None:
            return Response(
                {"detail": "latitude ve longitude alanlari zorunludur."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError):
            return Response(
                {"detail": "latitude/longitude sayisal olmalidir."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        TechnicianLocation.objects.create(
            tenant=technician.tenant,
            technician=technician.user,
            location=location_text or f"{latitude}, {longitude}",
            latitude=latitude,
            longitude=longitude,
        )

        return Response(
            {
                "detail": "Konum kaydedildi.",
                "latitude": latitude,
                "longitude": longitude,
            },
            status=status.HTTP_201_CREATED,
        )

class TechnicianLocationTrackingView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _resolve_technician(self, request):
        technician_id = request.data.get("technician")

        if technician_id:
            technician = get_object_or_404(_technician_queryset(request), id=technician_id)
            user = request.user
            is_admin = bool(user.is_superuser or user.is_staff or getattr(user, "user_type", "") == "admin")
            if not is_admin and technician.user_id != user.id:
                raise PermissionDenied("Bu teknisyen icin konum kaydi olusturma yetkiniz yok.")
            return technician

        technician = Technician.objects.filter(user=request.user, user__tenant=_request_tenant(request)).first()
        if technician:
            return technician

        return None

    def post(self, request):
        technician = self._resolve_technician(request)
        if not technician:
            return Response(
                {"technician": ["Teknisyen profili bulunamadi."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        latitude = request.data.get("latitude")
        longitude = request.data.get("longitude")
        if latitude is None or longitude is None:
            return Response(
                {"detail": "latitude ve longitude alanlari zorunludur."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError):
            return Response(
                {"detail": "latitude/longitude sayisal olmalidir."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = None
        service_id = request.data.get("service")
        if service_id:
            service = get_object_or_404(Service.objects.filter(customer__tenant=_request_tenant(request)), id=service_id)

        customer = service.customer if service and service.customer else None

        customer_latitude = request.data.get("customer_latitude")
        customer_longitude = request.data.get("customer_longitude")

        try:
            customer_latitude = float(customer_latitude) if customer_latitude is not None else None
            customer_longitude = float(customer_longitude) if customer_longitude is not None else None
        except (TypeError, ValueError):
            return Response(
                {"detail": "customer_latitude/customer_longitude sayisal olmalidir."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tracked_at = parse_iso_datetime(request.data.get("tracked_at")) or timezone.now()

        radius_meters = request.data.get("radius_meters", ARRIVAL_RADIUS_METERS_DEFAULT)
        try:
            radius_meters = float(radius_meters)
        except (TypeError, ValueError):
            radius_meters = ARRIVAL_RADIUS_METERS_DEFAULT

        if radius_meters <= 0:
            radius_meters = ARRIVAL_RADIUS_METERS_DEFAULT

        location_text = request.data.get("location") or f"{latitude}, {longitude}"

        TechnicianLocation.objects.create(
            technician=technician.user,
            location=location_text,
            latitude=latitude,
            longitude=longitude,
        )

        active_log = LocationLog.objects.filter(
            user=technician.user,
            service=service,
            left_at__isnull=True,
        ).order_by("-arrived_at").first()

        if active_log and customer_latitude is None:
            customer_latitude = active_log.customer_latitude
        if active_log and customer_longitude is None:
            customer_longitude = active_log.customer_longitude

        if customer_latitude is None or customer_longitude is None:
            return Response(
                {
                    "detail": "Musteri konumu olmadan varis/ayrilis tespiti yapilamaz. customer_latitude ve customer_longitude gonderin.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        distance = haversine_distance_meters(
            latitude,
            longitude,
            customer_latitude,
            customer_longitude,
        )
        is_within_radius = distance <= radius_meters

        event_type = None
        log = active_log

        with transaction.atomic():
            if is_within_radius:
                if not log:
                    log = LocationLog.objects.create(
                        user=technician.user,
                        technician=technician,
                        service=service,
                        customer=customer,
                        latitude=latitude,
                        longitude=longitude,
                        customer_latitude=customer_latitude,
                        customer_longitude=customer_longitude,
                        last_distance_meters=distance,
                        arrived_at=tracked_at,
                        last_seen_at=tracked_at,
                    )
                    event_type = LocationLog.EVENT_ARRIVED
                else:
                    log.latitude = latitude
                    log.longitude = longitude
                    log.customer_latitude = customer_latitude
                    log.customer_longitude = customer_longitude
                    log.last_distance_meters = distance
                    log.last_seen_at = tracked_at
                    log.save(
                        update_fields=[
                            "latitude",
                            "longitude",
                            "customer_latitude",
                            "customer_longitude",
                            "last_distance_meters",
                            "last_seen_at",
                            "updated_at",
                        ]
                    )
                    event_type = LocationLog.EVENT_STAYING
            elif log:
                log.latitude = latitude
                log.longitude = longitude
                log.last_distance_meters = distance
                log.last_seen_at = tracked_at
                log.left_at = tracked_at
                log.save(
                    update_fields=[
                        "latitude",
                        "longitude",
                        "last_distance_meters",
                        "last_seen_at",
                        "left_at",
                        "updated_at",
                    ]
                )
                event_type = LocationLog.EVENT_LEFT

        serialized_log = LocationLogSerializer(log).data if log else None
        return Response(
            {
                "event_type": event_type,
                "distance_meters": round(distance, 2),
                "radius_meters": round(radius_meters, 2),
                "is_within_radius": is_within_radius,
                "log": serialized_log,
            },
            status=status.HTTP_200_OK,
        )


class LocationLogListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        queryset = LocationLog.objects.select_related(
            "user",
            "technician",
            "technician__user",
            "service",
            "customer",
        )
        queryset = queryset.filter(user__tenant=_request_tenant(request))

        technician_id = request.query_params.get("technician")
        service_id = request.query_params.get("service")
        date_from = parse_iso_date(request.query_params.get("date_from"))
        date_to = parse_iso_date(request.query_params.get("date_to"))
        include_open = request.query_params.get("include_open", "true").lower() != "false"

        if technician_id:
            queryset = queryset.filter(technician_id=technician_id, technician__user__tenant=_request_tenant(request))
        if service_id:
            queryset = queryset.filter(service_id=service_id, service__customer__tenant=_request_tenant(request))
        if date_from:
            queryset = queryset.filter(arrived_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(arrived_at__date__lte=date_to)
        if not include_open:
            queryset = queryset.filter(left_at__isnull=False)

        user = request.user
        is_admin = bool(user.is_superuser or user.is_staff or getattr(user, "user_type", "") == "admin")
        if not is_admin:
            queryset = queryset.filter(user=user)

        serializer = LocationLogSerializer(queryset.order_by("-arrived_at"), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class TechnicianShiftListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _resolve_technician(self, request):
        technician_id = request.query_params.get("technician")
        if technician_id:
            return get_object_or_404(_technician_queryset(request), id=technician_id)

        current = Technician.objects.filter(user=request.user, user__tenant=_request_tenant(request)).first()
        if current:
            return current
        return None

    def get(self, request):
        technician = self._resolve_technician(request)
        if not technician:
            return Response({"detail": "Teknisyen profili bulunamadi."}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        is_admin = bool(user.is_superuser or user.is_staff or getattr(user, "user_type", "") == "admin")
        if not is_admin and technician.user_id != user.id:
            raise PermissionDenied("Bu teknisyenin mesai verilerini gorme yetkiniz yok.")

        month = request.query_params.get("month")
        start_date = parse_iso_date(request.query_params.get("start_date"))
        end_date = parse_iso_date(request.query_params.get("end_date"))

        if month and (not start_date or not end_date):
            month_start, month_end = month_date_range(month)
            if month_start and month_end:
                start_date = start_date or month_start
                end_date = end_date or month_end

        queryset = TechnicianShift.objects.filter(technician=technician.user)
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)

        rows = queryset.order_by("-date", "-start_time")
        serialized = TechnicianShiftSerializer(rows, many=True).data

        output = []
        for row in serialized:
            shift_status = "completed" if row.get("end_time") else "in_progress"
            output.append(
                {
                    **row,
                    "shift_status": shift_status,
                    "technician_profile_id": str(technician.id),
                    "technician_name": technician.user.get_full_name(),
                }
            )

        return Response(output, status=status.HTTP_200_OK)


class TechnicianWorkingHoursSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        technician_id = request.query_params.get("technician")
        if not technician_id:
            return Response({"detail": "technician parametresi zorunludur."}, status=status.HTTP_400_BAD_REQUEST)

        technician = get_object_or_404(_technician_queryset(request), id=technician_id)

        user = request.user
        is_admin = bool(user.is_superuser or user.is_staff or getattr(user, "user_type", "") == "admin")
        if not is_admin and technician.user_id != user.id:
            raise PermissionDenied("Bu teknisyenin verilerini gorme yetkiniz yok.")

        month = request.query_params.get("month")
        start_date = parse_iso_date(request.query_params.get("start_date"))
        end_date = parse_iso_date(request.query_params.get("end_date"))
        include_open = request.query_params.get("include_open", "true").lower() != "false"

        if month and (not start_date or not end_date):
            month_start, month_end = month_date_range(month)
            if month_start and month_end:
                start_date = start_date or month_start
                end_date = end_date or month_end

        shift_qs = TechnicianShift.objects.filter(technician=technician.user)
        if start_date:
            shift_qs = shift_qs.filter(date__gte=start_date)
        if end_date:
            shift_qs = shift_qs.filter(date__lte=end_date)

        shifts = TechnicianShiftSerializer(shift_qs.order_by("-date", "-start_time"), many=True).data
        shift_rows = []
        for row in shifts:
            shift_status = "completed" if row.get("end_time") else "in_progress"
            shift_rows.append(
                {
                    **row,
                    "shift_status": shift_status,
                    "technician_profile_id": str(technician.id),
                    "technician_name": technician.user.get_full_name(),
                }
            )

        location_qs = LocationLog.objects.select_related(
            "user",
            "technician",
            "technician__user",
            "service",
            "customer",
        ).filter(
            user__tenant=_request_tenant(request),
            technician=technician,
        )
        if start_date:
            location_qs = location_qs.filter(arrived_at__date__gte=start_date)
        if end_date:
            location_qs = location_qs.filter(arrived_at__date__lte=end_date)
        if not include_open:
            location_qs = location_qs.filter(left_at__isnull=False)
        if not is_admin:
            location_qs = location_qs.filter(user=user)

        location_rows = LocationLogSerializer(location_qs.order_by("-arrived_at"), many=True).data
        return Response(
            {
                "shifts": shift_rows,
                "location_logs": location_rows,
            },
            status=status.HTTP_200_OK,
        )


class TechnicianShiftStartView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _resolve_technician(self, request):
        technician_id = request.data.get("technician")
        if technician_id:
            technician = get_object_or_404(_technician_queryset(request), id=technician_id)
            user = request.user
            is_admin = bool(user.is_superuser or user.is_staff or getattr(user, "user_type", "") == "admin")
            if not is_admin and technician.user_id != user.id:
                raise PermissionDenied("Bu teknisyen icin mesai baslatma yetkiniz yok.")
            return technician

        technician = Technician.objects.filter(user=request.user, user__tenant=_request_tenant(request)).first()
        if technician:
            return technician
        return None

    def post(self, request):
        technician = self._resolve_technician(request)
        if not technician:
            return Response({"detail": "Teknisyen profili bulunamadi."}, status=status.HTTP_400_BAD_REQUEST)

        now = parse_iso_datetime(request.data.get("timestamp")) or timezone.now()
        shift_date = local_date_from_datetime(now)

        shift = (
            TechnicianShift.objects.filter(
                technician=technician.user,
                end_time__isnull=True,
            )
            .order_by("-date", "-start_time")
            .first()
        )
        created = False

        if shift:
            updates = []
            if not shift.start_time:
                shift.start_time = now
                updates.append("start_time")
            expected_shift_date = local_date_from_datetime(shift.start_time)
            if shift.date != expected_shift_date:
                shift.date = expected_shift_date
                updates.append("date")
            if updates:
                shift.save(update_fields=updates)
        else:
            shift = TechnicianShift.objects.filter(
                technician=technician.user,
                date=shift_date,
            ).order_by("-updated_at").first()

            if shift:
                shift.end_time = None
                update_fields = ["end_time"]
                expected_shift_date = local_date_from_datetime(shift.start_time or now)
                if shift.date != expected_shift_date:
                    shift.date = expected_shift_date
                    update_fields.append("date")
                shift.save(update_fields=update_fields)
            else:
                shift = TechnicianShift.objects.create(
                    technician=technician.user,
                    date=shift_date,
                    start_time=now,
                    end_time=None,
                )
                created = True

        # Mesai başlangıcında admin/yöneticilere bildirim gönder.
        actor_name = technician.user.get_full_name() or technician.user.email
        start_time_label = timezone.localtime(now).strftime("%H:%M")
        manager_users = User.objects.filter(
            is_active=True,
        ).filter(
            Q(is_superuser=True) | Q(is_staff=True) | Q(user_type="admin")
        ).exclude(id=technician.user_id)

        # Eğer teknisyen aynı zamanda admin ise exclude sonrası liste boş kalabilir.
        # Bu durumda bildirimi tamamen kaçırmamak için admin listesine geri düş.
        if not manager_users.exists():
            manager_users = User.objects.filter(
                is_active=True,
            ).filter(
                Q(is_superuser=True) | Q(is_staff=True) | Q(user_type="admin")
            )

        if manager_users.exists():
            try:
                create_bulk_notification(
                    users=manager_users,
                    title="Teknisyen Mesai Başlangıcı",
                    message=f"{actor_name} saat {start_time_label} itibarıyla mesaiye başladı.",
                    related_id=str(shift.id),
                    related_screen="MyShifts",
                )
            except Exception:
                # Bildirim hatası mesai başlatmayı bloklamamalı.
                logger.exception("Mesai başlangıç bildirimi gönderilirken hata oluştu.")

        # Teknisyene de bildirim gönder
        try:
            create_notification(
                user=technician.user,
                title="Mesai Başladı",
                message=f"Saat {start_time_label} itibarıyla mesainiz başladı. İyi çalışmalar!",
                related_id=str(shift.id),
                related_screen="MyShifts",
            )
        except Exception:
            logger.exception("Teknisyene mesai başlangıç bildirimi gönderilirken hata oluştu.")

        data = build_shift_payload(shift, technician)
        return Response(data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class TechnicianShiftStopView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _resolve_technician(self, request):
        technician_id = request.data.get("technician")
        if technician_id:
            technician = get_object_or_404(_technician_queryset(request), id=technician_id)
            user = request.user
            is_admin = bool(user.is_superuser or user.is_staff or getattr(user, "user_type", "") == "admin")
            if not is_admin and technician.user_id != user.id:
                raise PermissionDenied("Bu teknisyen icin mesai bitirme yetkiniz yok.")
            return technician

        technician = Technician.objects.filter(user=request.user, user__tenant=_request_tenant(request)).first()
        if technician:
            return technician
        return None

    def post(self, request):
        technician = self._resolve_technician(request)
        if not technician:
            return Response({"detail": "Teknisyen profili bulunamadi."}, status=status.HTTP_400_BAD_REQUEST)

        now = parse_iso_datetime(request.data.get("timestamp")) or timezone.now()

        open_shift = (
            TechnicianShift.objects.filter(technician=technician.user, end_time__isnull=True)
            .order_by("-date", "-start_time")
            .first()
        )
        if not open_shift:
            return Response({"detail": "Bitirilecek aktif mesai bulunamadi."}, status=status.HTTP_404_NOT_FOUND)

        if now < open_shift.start_time:
            now = timezone.now()

        open_shift.end_time = now
        open_shift.save(update_fields=["end_time"])

        # Mesai bitişinde admin/yöneticilere bildirim gönder.
        actor_name = technician.user.get_full_name() or technician.user.email
        end_time_label = timezone.localtime(now).strftime("%H:%M")
        manager_users = User.objects.filter(
            is_active=True,
        ).filter(
            Q(is_superuser=True) | Q(is_staff=True) | Q(user_type="admin")
        ).exclude(id=technician.user_id)

        if not manager_users.exists():
            manager_users = User.objects.filter(
                is_active=True,
            ).filter(
                Q(is_superuser=True) | Q(is_staff=True) | Q(user_type="admin")
            )

        if manager_users.exists():
            try:
                create_bulk_notification(
                    users=manager_users,
                    title="Teknisyen Mesai Bitişi",
                    message=f"{actor_name} saat {end_time_label} itibarıyla mesaisini bitirdi.",
                    related_id=str(open_shift.id),
                    related_screen="MyShifts",
                )
            except Exception:
                logger.exception("Mesai bitiş bildirimi gönderilirken hata oluştu.")

        # Teknisyene de bildirim gönder
        try:
            create_notification(
                user=technician.user,
                title="Mesai Bitti",
                message=f"Saat {end_time_label} itibarıyla mesainiz bitti. İyi dinlenmeler!",
                related_id=str(open_shift.id),
                related_screen="MyShifts",
            )
        except Exception:
            logger.exception("Teknisyene mesai bitiş bildirimi gönderilirken hata oluştu.")

        data = build_shift_payload(open_shift, technician)
        return Response(data, status=status.HTTP_200_OK)


class TechnicianAttendanceListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        technician_id = request.query_params.get("technician")
        month = request.query_params.get("month")
        start_date = parse_iso_date(request.query_params.get("start_date"))
        end_date = parse_iso_date(request.query_params.get("end_date"))

        if month:
            month_start, month_end = month_date_range(month)
            if month_start and month_end:
                end_date = month_end

        include_shift = request.query_params.get("include_shift", "true").lower() != "false"

        technician = None
        queryset = TechnicianAttendance.objects.select_related("technician", "technician__user")

        if technician_id:
            technician = get_object_or_404(_technician_queryset(request), id=technician_id)
            queryset = queryset.filter(technician=technician)
        else:
            queryset = queryset.filter(technician__user__tenant=_request_tenant(request))

        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)

        rows = list(queryset.order_by("date"))
        data = TechnicianAttendanceSerializer(rows, many=True).data

        if include_shift and technician and start_date and end_date:
            existing_dates = {row.date for row in rows}
            shifts = TechnicianShift.objects.filter(
                technician=technician.user,
                date__gte=start_date,
                date__lte=end_date,
            ).order_by("date")

            for shift in shifts:
                if shift.date in existing_dates:
                    continue

                data.append(
                    {
                        "id": f"shift-{shift.id}",
                        "technician": str(technician.id),
                        "technician_name": technician.user.get_full_name(),
                        "date": shift.date.isoformat(),
                        "status": TechnicianAttendance.STATUS_WORKED,
                        "start_time": shift.start_time.time().isoformat() if shift.start_time else None,
                        "end_time": shift.end_time.time().isoformat() if shift.end_time else None,
                        "note": "Mesai kaydindan otomatik getirildi.",
                        "source": TechnicianAttendance.SOURCE_SHIFT,
                        "is_derived": True,
                    }
                )

        data.sort(key=lambda item: item.get("date") or "")
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):
        technician_id = request.data.get("technician")
        attendance_date = parse_iso_date(request.data.get("date"))
        status_value = (request.data.get("status") or TechnicianAttendance.STATUS_WORKED).strip().lower()

        if not technician_id:
            return Response({"technician": ["Teknisyen zorunludur."]}, status=status.HTTP_400_BAD_REQUEST)
        if not attendance_date:
            return Response({"date": ["Gecerli tarih formati girin (YYYY-MM-DD)."]}, status=status.HTTP_400_BAD_REQUEST)
        if status_value not in dict(TechnicianAttendance.STATUS_CHOICES):
            return Response({"status": ["Gecersiz durum degeri."]}, status=status.HTTP_400_BAD_REQUEST)

        technician = get_object_or_404(_technician_queryset(request), id=technician_id)

        defaults = {
            "status": status_value,
            "start_time": parse_iso_time(request.data.get("start_time")),
            "end_time": parse_iso_time(request.data.get("end_time")),
            "note": request.data.get("note") or "",
            "source": TechnicianAttendance.SOURCE_MANUAL,
        }

        attendance, created = TechnicianAttendance.objects.update_or_create(
            technician=technician,
            date=attendance_date,
            defaults=defaults,
        )

        sync_shift_from_attendance(attendance)

        serializer = TechnicianAttendanceSerializer(attendance)
        return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class TechnicianAttendanceDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        attendance = get_object_or_404(
            TechnicianAttendance.objects.filter(technician__user__tenant=_request_tenant(request)),
            id=pk,
        )
        serializer = TechnicianAttendanceSerializer(attendance, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer.save(source=TechnicianAttendance.SOURCE_MANUAL)
        attendance.refresh_from_db()
        sync_shift_from_attendance(attendance)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        attendance = get_object_or_404(
            TechnicianAttendance.objects.filter(technician__user__tenant=_request_tenant(request)),
            id=pk,
        )
        attendance.delete()
        return Response({"detail": "Devam kaydi silindi."}, status=status.HTTP_200_OK)


class TechnicianOnlineStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        technician = Technician.objects.filter(user=request.user, user__tenant=_request_tenant(request)).first()
        if not technician:
            return Response(
                {"detail": "Teknisyen profili yok, online durum guncellenmedi.", "skipped": True},
                status=status.HTTP_200_OK,
            )

        is_online = bool(request.data.get("is_online", True))
        technician.is_online = is_online
        technician.last_online = timezone.now()
        technician.save(update_fields=["is_online", "last_online", "updated_at"])

        return Response(
            {
                "id": str(technician.id),
                "is_online": technician.is_online,
                "last_online": technician.last_online,
            },
            status=status.HTTP_200_OK,
        )
