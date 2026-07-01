import base64
import binascii
import re
import unicodedata
import uuid
from urllib.parse import quote, urlencode, urljoin, urlparse

from django.conf import settings
from django.core.files.base import ContentFile
from django.core import signing
from django.core.signing import BadSignature, SignatureExpired
from django.core.mail import EmailMessage
from django.db.models import Prefetch, Q
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import F
from config.models import CompanyConfig

from .models import (
    Brand,
    DeviceType,
    Model,
    PaymentMethod,
    Service,
    ServiceOperations,
    ServicePayment,
    ServicePhoto,
    ServiceSignature,
    ServiceOperationTemplate,
    ServiceStatus,
    WarrantyCertificate,
)
from technicians.models import Technician
from .permissions import IsServiceManager
from .serializers import (
    BrandSerializer,
    DeviceTypeSerializer,
    ModelSerializer,
    PaymentMethodSerializer,
    PublicServiceSerializer,
    ServiceOperationTemplateSerializer,
    ServiceOperationsSerializer,
    ServicePaymentSerializer,
    ServicePhotoSerializer,
    ServiceSerializer,
    ServiceSignatureSerializer,
    ServiceStatusSerializer,
    WarrantyCertificateSerializer,
)
from .models import ServiceTimeline
from .pdf_utils import generate_service_form_pdf, generate_warranty_certificate_pdf
from notifications.services import create_notification


class SerializerAPIView(APIView):
    serializer_class = None

    def get_serializer(self, *args, **kwargs):
        kwargs.setdefault("context", {"request": self.request})
        if not self.serializer_class:
            raise ValueError("serializer_class tanımlı değil.")
        return self.serializer_class(*args, **kwargs)


def _request_tenant(request):
    return getattr(getattr(request, "user", None), "tenant", None)


def _request_data_with_files(request):
    data = request.data.copy()
    if request.FILES:
        for key, file_obj in request.FILES.items():
            data[key] = file_obj
    return data


def _file_from_base64(raw_value, fallback_name):
    if not raw_value:
        return None
    value = str(raw_value)
    if ';base64,' in value:
        value = value.split(';base64,', 1)[1]
    try:
        decoded = base64.b64decode(value)
    except (TypeError, ValueError, binascii.Error):
        return None
    return ContentFile(decoded, name=fallback_name)


def _service_tenant_queryset(request):
    tenant = _request_tenant(request)
    return Service.objects.filter(tenant=tenant)


def _status_label(value):
    if isinstance(value, ServiceStatus):
        return value.name
    mapping = {
        'new': 'Yeni',
        'assigned': 'Atandi',
        'in_progress': 'İşlemde',
        'postponed': 'Ertelendi',
        'completed': 'Tamamlandi',
        'cancelled': 'İptal',
    }
    return mapping.get(value, str(value or '-'))


def _filter_by_status_code(qs, status_code):
    if status_code and status_code != 'all':
        return qs.filter(status__code=status_code)
    return qs


def _normalize_phone_for_whatsapp(raw_phone):
    phone = str(raw_phone or '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    if phone.startswith('+'):
        phone = phone[1:]
    if phone.startswith('0'):
        phone = f'90{phone[1:]}'
    return ''.join(ch for ch in phone if ch.isdigit())


PUBLIC_SERVICE_TOKEN_SALT = "services.public.access.v1"


def build_public_service_token(service):
    if not service:
        return None
    signer = signing.TimestampSigner(salt=PUBLIC_SERVICE_TOKEN_SALT)
    return signer.sign(str(service.id))


def resolve_public_service_token(raw_token, max_age_seconds=60 * 60 * 24 * 30):
    if not raw_token:
        return None
    signer = signing.TimestampSigner(salt=PUBLIC_SERVICE_TOKEN_SALT)
    try:
        service_id = signer.unsign(raw_token, max_age=max_age_seconds)
        return service_id
    except (BadSignature, SignatureExpired):
        return None


def _service_public_tenant(service):
    customer_tenant = getattr(getattr(service, "customer", None), "tenant", None)
    if customer_tenant:
        return customer_tenant
    technician_user = getattr(getattr(service, "technician", None), "user", None)
    return getattr(technician_user, "tenant", None)


def _resolve_public_panel_base_url(service, request=None):
    tenant = _service_public_tenant(service)
    if tenant:
        config = CompanyConfig.objects.filter(tenant=tenant).only("panel_url").first()
        panel_url = str(getattr(config, "panel_url", "") or "").strip() if config else ""
        if panel_url:
            return panel_url.rstrip("/")

    frontend_url = str(getattr(settings, "FRONTEND_URL", "") or "").strip()
    if frontend_url:
        return frontend_url.rstrip("/")

    if request:
        origin = str(request.headers.get("Origin") or "").strip()
        if origin:
            return origin.rstrip("/")

        referer = str(request.headers.get("Referer") or "").strip()
        if referer:
            parsed_referer = urlparse(referer)
            if parsed_referer.scheme and parsed_referer.netloc:
                return f"{parsed_referer.scheme}://{parsed_referer.netloc}"

        host = request.get_host()
        if ':8000' in host:
            host = host.replace(':8000', ':5173')
        elif ':80' in host:
            pass # production
        return f"{request.scheme}://{host}"

    return ""


def _build_public_service_tracking_url(service, request=None):
    if not service:
        return ""
    access_token = build_public_service_token(service)
    query = urlencode({"access_token": access_token})
    path = f"service-tracking/{service.id}/?{query}"
    base_url = _resolve_public_panel_base_url(service, request=request)
    if base_url:
        return urljoin(f"{base_url}/", path)
    return f"/{path}"


def _format_service_schedule_label(value):
    if not value:
        return '-'
    value = timezone.localtime(value) if timezone.is_aware(value) else value
    return value.strftime('%d.%m.%Y %H:%M')


def _ascii_filename_part(value, fallback='servis'):
    raw = str(value or '').strip()
    if not raw:
        return fallback
    normalized = unicodedata.normalize('NFKD', raw).encode('ascii', 'ignore').decode('ascii')
    cleaned = re.sub(r'[^A-Za-z0-9-]+', '_', normalized).strip('_')
    return cleaned or fallback


def _build_service_pdf_filename(service):
    customer_name = getattr(service, 'customer_full_name', None) or getattr(getattr(service, 'customer', None), 'full_name', None)
    receipt_number = getattr(service, 'receipt_number', None) or getattr(service, 'id', None)
    scheduled_date = getattr(service, 'scheduled_date', None)
    if scheduled_date:
        scheduled_date = timezone.localtime(scheduled_date) if timezone.is_aware(scheduled_date) else scheduled_date
        date_part = scheduled_date.strftime('%Y-%m-%d')
    else:
        date_part = ''

    parts = [
        'servis_formu',
        _ascii_filename_part(customer_name, 'musteri'),
        _ascii_filename_part(receipt_number, 'servis'),
    ]
    if date_part:
        parts.append(date_part)
    return '_'.join(parts) + '.pdf'


def _build_download_disposition(filename):
    stem, dot, ext = filename.rpartition('.')
    safe_stem = _ascii_filename_part(stem or filename, 'servis_formu')
    ascii_fallback = f"{safe_stem}.{ext}" if dot else f"{safe_stem}.pdf"
    encoded_filename = quote(filename)
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded_filename}'


def _build_inline_disposition(filename):
    encoded_filename = quote(filename)
    return f'inline; filename="{filename}"; filename*=UTF-8\'\'{encoded_filename}'


def _build_service_status_whatsapp_url(service, new_status=None, request=None, status_changed=False, schedule_changed=False, scheduled_date=None):
    if not service:
        return None
    status_code = new_status or service.service_status
    status_label = _status_label(status_code)
    tracking_url = _build_public_service_tracking_url(service, request=request) or '-'
    appointment_label = _format_service_schedule_label(scheduled_date or service.scheduled_date)

    if schedule_changed and status_changed:
        message = (
            f"Servis Durumunuz {status_label} olarak değiştirildi.\n"
            f"Yeni randevu: {appointment_label}\n"
            f"Takip etmek için: {tracking_url}"
        )
    elif schedule_changed:
        message = (
            f"Servis randevunuz {appointment_label} olarak güncellendi.\n"
            f"Takip etmek için: {tracking_url}"
        )
    else:
        message = (
            f"Merhaba, servisinizin mevcut durumu: {status_label}\n"
            f"Servis süreçlerinizi aşağıdaki bağlantıdan takip edebilirsiniz:\n"
            f"{tracking_url}"
        )

    phone = _normalize_phone_for_whatsapp(service.customer_phone)
    if phone:
        return f"https://wa.me/{phone}?text={quote(message)}"
    return f"https://wa.me/?text={quote(message)}"


def _build_service_technician_whatsapp_url(service, request=None):
    """Servis atanan teknisyene gonderilecek WhatsApp mesaj linki."""
    if not service or not service.technician:
        return None
    technician = service.technician
    technician_user = getattr(technician, 'user', None)
    if not technician_user:
        return None

    appointment_label = _format_service_schedule_label(service.scheduled_date)
    customer_name = service.customer_full_name or 'Müşteri'
    device_label = (service.device_model.name if service.device_model else None) or 'Cihaz'
    issue_label = service.fault_description or '-'
    tracking_url = _build_public_service_tracking_url(service, request=request) or '-'
    technician_name = technician_user.get_full_name() or technician_user.username or 'Teknisyen'

    message = (
        f"Merhaba {technician_name},\n"
        f"Size yeni bir servis atandi.\n"
        f"Musteri: {customer_name}\n"
        f"Cihaz: {device_label}\n"
        f"Sikayet: {issue_label}\n"
        f"Randevu: {appointment_label}"
    )

    phone = _normalize_phone_for_whatsapp(getattr(technician_user, 'phone', None))
    if phone:
        return f"https://wa.me/{phone}?text={quote(message)}"
    return f"https://wa.me/?text={quote(message)}"


def _create_timeline_if_status_changed(service, old_status):
    if old_status != service.service_status:
        ServiceTimeline.objects.create(
            service=service,
            old_status=old_status or '',
            new_status=service.service_status or '',
        )


def _notify_technician_assignment(service, old_technician_id=None):
    technician = getattr(service, 'technician', None)
    technician_user = getattr(technician, 'user', None)
    new_technician_id = getattr(service, 'technician_id', None)
    if old_technician_id and str(old_technician_id) == str(new_technician_id):
        return

    old_technician_user = None
    if old_technician_id:
        old_technician = Technician.objects.select_related('user').filter(pk=old_technician_id).first()
        old_technician_user = getattr(old_technician, 'user', None)

    customer_name = service.customer_full_name or 'Müşteri'
    service_no = service.receipt_number or '-'

    # Yeni teknisyene: pozitif atama/güncelleme mesajı
    if technician_user:
        if old_technician_user and old_technician_user.id != technician_user.id:
            title = 'Servis ataması güncellendi'
            message = f"#{service_no} no'lu servis size devredildi. Müşteri: {customer_name}."
        else:
            title = 'Yeni servis ataması'
            message = f"#{service_no} no'lu servis size atandı. Müşteri: {customer_name}."
        create_notification(
            user=technician_user,
            title=title,
            message=message,
            related_id=str(service.id),
            related_screen='service_detail',
        )

    # Eski teknisyene: kırıcı olmayan, bilgilendirici mesaj
    if old_technician_user and (not technician_user or old_technician_user.id != technician_user.id):
        if technician_user:
            message = f"#{service_no} no'lu servis görevi planlama güncellemesiyle başka bir teknisyene devredildi."
        else:
            message = f"#{service_no} no'lu servis görevi planlama güncellemesi nedeniyle atama listesinden çıkarıldı."
        create_notification(
            user=old_technician_user,
            title='Servis görevinde güncelleme',
            message=message,
            related_id=str(service.id),
            related_screen='service_detail',
        )


def _notify_status_change_by_actor(service, actor_user, old_status):
    if not actor_user or old_status == service.service_status:
        return

    service_no = service.receipt_number or '-'
    old_label = _status_label(old_status)
    new_label = _status_label(service.service_status)
    customer_name = service.customer_full_name or 'Müşteri'

    actor_is_admin_like = bool(actor_user.is_staff or getattr(actor_user, 'user_type', '') == 'admin')
    actor_is_technician = getattr(actor_user, 'user_type', '') == 'technician'

    if actor_is_admin_like:
        technician_user = getattr(getattr(service, 'technician', None), 'user', None)
        if technician_user and technician_user.id != actor_user.id:
            create_notification(
                user=technician_user,
                title='Servis durumu güncellendi',
                message=f"#{service_no} no'lu servis durumu {old_label} -> {new_label} olarak güncellendi. Müşteri: {customer_name}.",
                related_id=str(service.id),
                related_screen='service_detail',
            )
        return

    if actor_is_technician:
        user_model = get_user_model()
        admin_users = user_model.objects.filter(
            is_active=True
        ).filter(
            Q(user_type='admin') | Q(is_staff=True)
        ).exclude(pk=actor_user.pk)

        for admin_user in admin_users:
            create_notification(
                user=admin_user,
                title='Teknisyen servis durumu güncelledi',
                message=f"#{service_no} no'lu servis durumu {old_label} -> {new_label}. Teknisyen: {actor_user.get_full_name()}.",
                related_id=str(service.id),
                related_screen='service_detail',
            )


#admin başı

class BrandListCreateView(SerializerAPIView):
    serializer_class = BrandSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = self.get_serializer(Brand.objects.filter(tenant=_request_tenant(request)), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save(tenant=_request_tenant(request))
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def patch(self, request):
        try:
            brand = Brand.objects.get(pk=request.data["pk"], tenant=_request_tenant(request))
        except Brand.DoesNotExist:
            return Response({"error": "Brand not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(brand, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def delete(self, request):
        try:
            brand = Brand.objects.get(pk=request.data["pk"], tenant=_request_tenant(request))
        except Brand.DoesNotExist:
            return Response({"error": "Marka bulunamadı"}, status=status.HTTP_404_NOT_FOUND)
        brand.delete()
        return Response({"message": "Marka başarıyla silindi"}, status=status.HTTP_200_OK)

class DeviceTypeListCreateView(SerializerAPIView):
    serializer_class = DeviceTypeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = self.get_serializer(DeviceType.objects.filter(tenant=_request_tenant(request)), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save(tenant=_request_tenant(request))
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def patch(self, request):
        try:
            device_type = DeviceType.objects.get(pk=request.data["pk"], tenant=_request_tenant(request))
        except DeviceType.DoesNotExist:
            return Response({"error": "Cihaz tipi bulunamadı"}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(device_type, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def delete(self, request):
        try:
            device_type = DeviceType.objects.get(pk=request.data["pk"], tenant=_request_tenant(request))
        except DeviceType.DoesNotExist:
            return Response({"error": "Cihaz tipi bulunamadı"}, status=status.HTTP_404_NOT_FOUND)
        device_type.delete()
        return Response({"message": "Cihaz tipi başarıyla silindi"}, status=status.HTTP_200_OK)

class ServiceStatusListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        tenant = _request_tenant(request)
        statuses = ServiceStatus.objects.filter(is_active=True).filter(
            Q(tenant=tenant) | Q(tenant__isnull=True)
        ).order_by('sort_order', 'name')
        serializer = ServiceStatusSerializer(statuses.distinct(), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class ModelListCreateView(SerializerAPIView):
    serializer_class = ModelSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = self.get_serializer(Model.objects.filter(tenant=_request_tenant(request)), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save(tenant=_request_tenant(request))
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def patch(self, request):
        try:
            model = Model.objects.get(pk=request.data["pk"], tenant=_request_tenant(request))
        except Model.DoesNotExist:
            return Response({"error": "Model bulunamadı"}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(model, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def delete(self, request):
        try:
            model = Model.objects.get(pk=request.data["pk"], tenant=_request_tenant(request))
        except Model.DoesNotExist:
            return Response({"error": "Model bulunamadı"}, status=status.HTTP_404_NOT_FOUND)
        model.delete()
        return Response({"message": "Model başarıyla silindi"}, status=status.HTTP_200_OK)

class PaymentMethodListCreateView(SerializerAPIView):
    serializer_class = PaymentMethodSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = self.get_serializer(PaymentMethod.objects.filter(tenant=_request_tenant(request)), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save(tenant=_request_tenant(request))
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def patch(self, request):
        try:
            payment_method = PaymentMethod.objects.get(pk=request.data["pk"], tenant=_request_tenant(request))
        except PaymentMethod.DoesNotExist:
            return Response({"error": "Ödeme yöntemi bulunamadı"}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(payment_method, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def delete(self, request):
        try:
            payment_method = PaymentMethod.objects.get(pk=request.data["pk"], tenant=_request_tenant(request))
        except PaymentMethod.DoesNotExist:
            return Response({"error": "Ödeme yöntemi bulunamadı"}, status=status.HTTP_404_NOT_FOUND)
        payment_method.delete()
        return Response({"message": "Ödeme yöntemi başarıyla silindi"}, status=status.HTTP_200_OK)

class ServiceOperationsListCreateView(SerializerAPIView):
    serializer_class = ServiceOperationsSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = self.get_serializer(
            ServiceOperations.objects.filter(service__customer__tenant=_request_tenant(request)),
            many=True,
        )
        return Response(serializer.data, status=status.HTTP_200_OK)
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def patch(self, request):
        try:
            service_operation = ServiceOperations.objects.get(
                pk=request.data["pk"],
                service__customer__tenant=_request_tenant(request),
            )
        except ServiceOperations.DoesNotExist:
            return Response({"error": "İşlem bulunamadı"}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(service_operation, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def delete(self, request):
        try:
            service_operation = ServiceOperations.objects.get(
                pk=request.data["pk"],
                service__customer__tenant=_request_tenant(request),
            )
        except ServiceOperations.DoesNotExist:
            return Response({"error": "İşlem bulunamadı"}, status=status.HTTP_404_NOT_FOUND)
        service_operation.delete()
        return Response({"message": "İşlem başarıyla silindi"}, status=status.HTTP_200_OK)

class ServiceOperationTemplateListCreateView(SerializerAPIView):
    serializer_class = ServiceOperationTemplateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self, request):
        user = request.user
        return ServiceOperationTemplate.objects.filter(
            Q(is_active=True),
            Q(created_by__isnull=True) | Q(created_by=user),
            tenant=_request_tenant(request),
        ).order_by('name', '-created_at')

    def get(self, request):
        serializer = self.get_serializer(self.get_queryset(request), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save(created_by=request.user, tenant=_request_tenant(request))
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request):
        try:
            template = ServiceOperationTemplate.objects.get(pk=request.data["pk"], tenant=_request_tenant(request))
        except ServiceOperationTemplate.DoesNotExist:
            return Response({"error": "Islem sablonu bulunamadi"}, status=status.HTTP_404_NOT_FOUND)

        if template.created_by and template.created_by != request.user and not request.user.is_staff:
            return Response({"error": "Bu sablonu duzenleme yetkiniz yok"}, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(template, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request):
        try:
            template = ServiceOperationTemplate.objects.get(pk=request.data["pk"], tenant=_request_tenant(request))
        except ServiceOperationTemplate.DoesNotExist:
            return Response({"error": "Islem sablonu bulunamadi"}, status=status.HTTP_404_NOT_FOUND)

        if template.created_by and template.created_by != request.user and not request.user.is_staff:
            return Response({"error": "Bu sablonu silme yetkiniz yok"}, status=status.HTTP_403_FORBIDDEN)

        template.delete()
        return Response({"message": "Islem sablonu silindi"}, status=status.HTTP_200_OK)


class ServicePaymentListCreateView(SerializerAPIView):
    serializer_class = ServicePaymentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = self.get_serializer(
            ServicePayment.objects.filter(service__customer__tenant=_request_tenant(request)),
            many=True,
        )
        return Response(serializer.data, status=status.HTTP_200_OK)
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def patch(self, request):
        try:
            service_payment = ServicePayment.objects.get(
                pk=request.data["pk"],
                service__customer__tenant=_request_tenant(request),
            )
        except ServicePayment.DoesNotExist:
            return Response({"error": "Ödeme bulunamadı"}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(service_payment, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def delete(self, request):
        try:
            service_payment = ServicePayment.objects.get(
                pk=request.data["pk"],
                service__customer__tenant=_request_tenant(request),
            )
        except ServicePayment.DoesNotExist:
            return Response({"error": "Ödeme bulunamadı"}, status=status.HTTP_404_NOT_FOUND)
        service_payment.delete()
        return Response({"message": "Ödeme başarıyla silindi"}, status=status.HTTP_200_OK)

class ServicePaymentRefundView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        payment_id = request.data.get("pk")
        reason = (request.data.get("reason") or "").strip()
        if not payment_id:
            return Response({"error": "Odeme kaydi secilmedi."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            service_payment = ServicePayment.objects.get(
                pk=payment_id,
                service__customer__tenant=_request_tenant(request),
            )
        except ServicePayment.DoesNotExist:
            return Response({"error": "Odeme bulunamadi"}, status=status.HTTP_404_NOT_FOUND)

        if reason:
            existing_note = (service_payment.note or '').strip()
            service_payment.note = f"{existing_note} | Iade nedeni: {reason}" if existing_note else f"Iade nedeni: {reason}"
            service_payment.save()

        # delete() iade ters kaydini olusturup odeme kaydini kaldirir.
        service_payment.delete()
        return Response({"message": "Odeme iade edildi ve ters kayit olusturuldu."}, status=status.HTTP_200_OK)
class ServicePhotoListCreateView(SerializerAPIView):
    serializer_class = ServicePhotoSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request):
        serializer = self.get_serializer(
            ServicePhoto.objects.filter(service__customer__tenant=_request_tenant(request)),
            many=True,
        )
        return Response(serializer.data, status=status.HTTP_200_OK)
    def post(self, request):
        data = _request_data_with_files(request)
        image_base64 = data.pop("image_base64", None)
        image_name = data.pop("image_name", None) or f"service_photo_{uuid.uuid4().hex}.jpg"
        if image_base64 and not data.get("image"):
            image_file = _file_from_base64(image_base64, image_name)
            if not image_file:
                return Response({"image": "Fotograf verisi okunamadi."}, status=status.HTTP_400_BAD_REQUEST)
            data["image"] = image_file
        serializer = self.get_serializer(data=data)
        if serializer.is_valid():
            serializer.save(tenant=_request_tenant(request))
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def patch(self, request):
        try:
            service_photo = ServicePhoto.objects.get(
                pk=request.data["pk"],
                service__customer__tenant=_request_tenant(request),
            )
        except ServicePhoto.DoesNotExist:
            return Response({"error": "Fotoğraf bulunamadı"}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(service_photo, data=_request_data_with_files(request), partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def delete(self, request):
        try:
            service_photo = ServicePhoto.objects.get(
                pk=request.data["pk"],
                service__customer__tenant=_request_tenant(request),
            )
        except ServicePhoto.DoesNotExist:
            return Response({"error": "Fotoğraf bulunamadı"}, status=status.HTTP_404_NOT_FOUND)
        service_photo.delete()
        return Response({"message": "Fotoğraf başarıyla silindi"}, status=status.HTTP_200_OK)


class ServiceSignatureListCreateView(SerializerAPIView):
    serializer_class = ServiceSignatureSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request):
        serializer = self.get_serializer(
            ServiceSignature.objects.filter(service__customer__tenant=_request_tenant(request)),
            many=True,
        )
        return Response(serializer.data, status=status.HTTP_200_OK)
    def post(self, request):
        data = _request_data_with_files(request)
        customer_base64 = data.pop("customer_signature_base64", None)
        technician_base64 = data.pop("technician_signature_base64", None)
        if customer_base64 and not data.get("customer_signature"):
            signature_file = _file_from_base64(customer_base64, f"customer_signature_{uuid.uuid4().hex}.png")
            if not signature_file:
                return Response({"customer_signature": "Musteri imzasi okunamadi."}, status=status.HTTP_400_BAD_REQUEST)
            data["customer_signature"] = signature_file
        if technician_base64 and not data.get("technician_signature"):
            signature_file = _file_from_base64(technician_base64, f"technician_signature_{uuid.uuid4().hex}.png")
            if not signature_file:
                return Response({"technician_signature": "Teknisyen imzasi okunamadi."}, status=status.HTTP_400_BAD_REQUEST)
            data["technician_signature"] = signature_file

        service_id = data.get("service")
        existing_signature = None
        if service_id:
            existing_signature = ServiceSignature.objects.filter(
                service_id=service_id,
                service__customer__tenant=_request_tenant(request),
            ).first()

        if existing_signature:
            serializer = self.get_serializer(existing_signature, data=data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(data=data)
        if serializer.is_valid():
            serializer.save(tenant=_request_tenant(request))
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def patch(self, request):
        try:
            service_signature = ServiceSignature.objects.get(
                pk=request.data["pk"],
                service__customer__tenant=_request_tenant(request),
            )
        except ServiceSignature.DoesNotExist:
            return Response({"error": "İmza bulunamadı"}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(service_signature, data=_request_data_with_files(request), partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def delete(self, request):
        try:
            service_signature = ServiceSignature.objects.get(
                pk=request.data["pk"],
                service__customer__tenant=_request_tenant(request),
            )
        except ServiceSignature.DoesNotExist:
            return Response({"error": "İmza bulunamadı"}, status=status.HTTP_404_NOT_FOUND)
        service_signature.delete()
        return Response({"message": "İmza başarıyla silindi"}, status=status.HTTP_200_OK)

class WarrantyCertificateListCreateView(SerializerAPIView):
    serializer_class = WarrantyCertificateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = self.get_serializer(
            WarrantyCertificate.objects.filter(service__customer__tenant=_request_tenant(request)),
            many=True,
        )
        return Response(serializer.data, status=status.HTTP_200_OK)
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def patch(self, request):
        try:
            warranty_certificate = WarrantyCertificate.objects.get(
                pk=request.data["pk"],
                service__customer__tenant=_request_tenant(request),
            )
        except WarrantyCertificate.DoesNotExist:
            return Response({"error": "Garanti belgesi bulunamadı"}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(warranty_certificate, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def delete(self, request):
        try:
            warranty_certificate = WarrantyCertificate.objects.get(
                pk=request.data["pk"],
                service__customer__tenant=_request_tenant(request),
            )
        except WarrantyCertificate.DoesNotExist:
            return Response({"error": "Garanti belgesi bulunamadı"}, status=status.HTTP_404_NOT_FOUND)
        warranty_certificate.delete()
        return Response({"message": "Garanti belgesi başarıyla silindi"}, status=status.HTTP_200_OK)

#teknisyen listesi
class TechnicianServiceListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self, request):
        user = request.user

        qs = _service_tenant_queryset(request).select_related(
            'customer', 'technician', 'technician__user'
        ).prefetch_related(
            'items', 'payments', 'photos', 'timeline'
        )

      
        qs = qs.filter(technician__user=user, tenant=_request_tenant(request))

        search = request.query_params.get('search')

        if search:
            if user.user_type == 'admin' or user.is_staff:
                pass
            else:
                qs = qs.filter(technician__user=user)

            qs = _filter_by_status_code(qs, request.query_params.get('status'))

            qs = qs.filter(
                Q(customer_full_name__icontains=search) |
                Q(receipt_number__icontains=search) |
                Q(customer_phone__icontains=search) |
                Q(customer_address__icontains=search)
            )
        else:
            date_param = request.query_params.get('date')
            if date_param:
                qs = qs.filter(scheduled_date__date=date_param)

            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')
            if start_date and end_date:
                qs = qs.filter(scheduled_date__date__range=[start_date, end_date])

            qs = _filter_by_status_code(qs, request.query_params.get('status'))

            customer_id = request.query_params.get('customer')
            if customer_id:
                qs = qs.filter(customer_id=customer_id)

        return qs.order_by(F("scheduled_date").desc(nulls_last=True))

    def get(self, request):
        queryset = self.get_queryset(request)

        serializer = ServiceSerializer(
            queryset,
            many=True,
            context={"request": request}
        )

        return Response(serializer.data)

    def post(self, request):
        serializer = ServiceSerializer(data=request.data, context={"request": request})

        if serializer.is_valid():
            serializer.save(tenant=_request_tenant(request))
            _notify_technician_assignment(serializer.instance, old_technician_id=None)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class TechnicianServiceRetrieveUpdateDestroyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self, request):
        user = request.user

        qs = _service_tenant_queryset(request).select_related(
            'customer', 'technician', 'technician__user'
        ).prefetch_related(
            'items', 'payments', 'photos', 'timeline'
        )

        if user.user_type == 'admin' or user.is_staff:
            pass
        else:
            qs = qs.filter(technician__user=user)

        return qs.order_by("-scheduled_date")

    def get(self, request, pk):
        service = get_object_or_404(self.get_queryset(request), pk=pk)
        serializer = ServiceSerializer(service, context={"request": request})
        return Response(serializer.data)

    def patch(self, request, pk):
        service = get_object_or_404(self.get_queryset(request), pk=pk)
        old_status = service.service_status
        old_technician_id = service.technician_id
        old_scheduled_date = service.scheduled_date
        serializer = ServiceSerializer(service, data=request.data, partial=True, context={"request": request})

        if serializer.is_valid():
            serializer.save()
            service.refresh_from_db()
            _create_timeline_if_status_changed(service, old_status)
            _notify_status_change_by_actor(service, request.user, old_status)
            _notify_technician_assignment(service, old_technician_id=old_technician_id)
            payload = serializer.data
            status_changed = old_status != service.service_status
            schedule_changed = old_scheduled_date != service.scheduled_date
            technician_changed = old_technician_id != service.technician_id
            if status_changed or schedule_changed:
                payload = {
                    **payload,
                    **({'status_changed': True} if status_changed else {}),
                    **({'schedule_changed': True} if schedule_changed else {}),
                    'whatsapp_status_url': _build_service_status_whatsapp_url(
                        service,
                        request=request,
                        new_status=service.service_status,
                        status_changed=status_changed,
                        schedule_changed=schedule_changed,
                        scheduled_date=service.scheduled_date,
                    ),
                }
            if technician_changed and service.technician_id:
                payload = {
                    **payload,
                    'technician_changed': True,
                    'whatsapp_technician_url': _build_service_technician_whatsapp_url(
                        service,
                        request=request,
                    ),
                }
            return Response(payload)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AdminServiceListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self, request):
        user = request.user

        qs = _service_tenant_queryset(request).select_related(
            'customer', 'technician', 'technician__user'
        ).prefetch_related(
            'items', 'payments', 'photos', 'timeline'
        )

        # 🔐 yetki
        qs = qs.all()

        # 🔍 search
        search = request.query_params.get('search')
        if search:
            qs = qs.filter(
                Q(customer_full_name__icontains=search) |
                Q(receipt_number__icontains=search) |
                Q(customer_phone__icontains=search)
            )

        technician = request.query_params.get('technician')
        if technician:
            qs = qs.filter(Q(technician_id=technician) | Q(technician__user_id=technician))

        customer_id = request.query_params.get('customer')
        if customer_id:
            qs = qs.filter(customer_id=customer_id)

        # 📅 Tarih aralığı filtresi (mobil ay bazlı fetch için)
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        if start_date and end_date:
            qs = qs.filter(scheduled_date__date__range=[start_date, end_date])

        return qs.order_by("-scheduled_date")

    def get(self, request):
        queryset = self.get_queryset(request)

        serializer = ServiceSerializer(
            queryset,
            many=True,
            context={"request": request}
        )

        return Response(serializer.data)

    def post(self, request):
        serializer = ServiceSerializer(data=request.data, context={"request": request})

        if serializer.is_valid():
            serializer.save(tenant=_request_tenant(request))
            _notify_technician_assignment(serializer.instance, old_technician_id=None)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request):
        service = get_object_or_404(self.get_queryset(request), pk=request.data.get("pk"))
        old_status = service.service_status
        old_technician_id = service.technician_id
        old_scheduled_date = service.scheduled_date

        # 🔐 yetki kontrolü
        user = request.user
        serializer = ServiceSerializer(
            service,
            data=request.data,
            partial=True,
            context={"request": request}
        )

        if serializer.is_valid():
            serializer.save()
            service.refresh_from_db()
            _create_timeline_if_status_changed(service, old_status)
            _notify_status_change_by_actor(service, request.user, old_status)
            _notify_technician_assignment(service, old_technician_id=old_technician_id)
            payload = serializer.data
            status_changed = old_status != service.service_status
            schedule_changed = old_scheduled_date != service.scheduled_date
            technician_changed = old_technician_id != service.technician_id
            if status_changed or schedule_changed:
                payload = {
                    **payload,
                    **({'status_changed': True} if status_changed else {}),
                    **({'schedule_changed': True} if schedule_changed else {}),
                    'whatsapp_status_url': _build_service_status_whatsapp_url(
                        service,
                        request=request,
                        new_status=service.service_status,
                        status_changed=status_changed,
                        schedule_changed=schedule_changed,
                        scheduled_date=service.scheduled_date,
                    ),
                }
            if technician_changed and service.technician_id:
                payload = {
                    **payload,
                    'technician_changed': True,
                    'whatsapp_technician_url': _build_service_technician_whatsapp_url(
                        service,
                        request=request,
                    ),
                }
            return Response(payload)

        return Response(serializer.errors, status=400)

    def delete(self, request):
        service = get_object_or_404(self.get_queryset(request), pk=request.data.get("pk"))

        # 🔐 yetki kontrolü
        user = request.user
        if not (user.is_superuser or user.user_type == "admin"):
            return Response({"error": "Silme yetkiniz yok"}, status=403)

        service.delete()
        return Response({"message": "Silindi"})



class AdminServiceRetrieveUpdateDestroyView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def get_queryset(self, request):
        user = request.user

        qs = _service_tenant_queryset(request).select_related(
            'customer', 'technician', 'technician__user'
        ).prefetch_related(
            'items', 'payments', 'photos', 'timeline'
        )
        qs = qs.all()
        return qs.order_by("-scheduled_date")
    
    def get(self, request, pk):
        service = get_object_or_404(self.get_queryset(request), pk=pk)
        serializer = ServiceSerializer(service, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def patch(self, request, pk):
        service = get_object_or_404(self.get_queryset(request), pk=pk)
        old_status = service.service_status
        old_technician_id = service.technician_id
        old_scheduled_date = service.scheduled_date
        serializer = ServiceSerializer(service, data=request.data, partial=True, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            service.refresh_from_db()
            _create_timeline_if_status_changed(service, old_status)
            _notify_status_change_by_actor(service, request.user, old_status)
            _notify_technician_assignment(service, old_technician_id=old_technician_id)
            payload = serializer.data
            status_changed = old_status != service.service_status
            schedule_changed = old_scheduled_date != service.scheduled_date
            technician_changed = old_technician_id != service.technician_id
            if status_changed or schedule_changed:
                payload = {
                    **payload,
                    **({'status_changed': True} if status_changed else {}),
                    **({'schedule_changed': True} if schedule_changed else {}),
                    'whatsapp_status_url': _build_service_status_whatsapp_url(
                        service,
                        request=request,
                        new_status=service.service_status,
                        status_changed=status_changed,
                        schedule_changed=schedule_changed,
                        scheduled_date=service.scheduled_date,
                    ),
                }
            if technician_changed and service.technician_id:
                payload = {
                    **payload,
                    'technician_changed': True,
                    'whatsapp_technician_url': _build_service_technician_whatsapp_url(
                        service,
                        request=request,
                    ),
                }
            return Response(payload)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, pk):
        service = get_object_or_404(self.get_queryset(request), pk=pk)
        service.delete()
        return Response({"message": "Servis başarıyla silindi"}, status=status.HTTP_200_OK)
    
class ServiceFormPDFView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        service = get_object_or_404(
            _service_tenant_queryset(request).select_related('customer', 'technician__user').prefetch_related('items', 'payments'),
            pk=pk,
        )
        pdf_buffer = generate_service_form_pdf(service)
        filename = _build_service_pdf_filename(service)
        response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = _build_download_disposition(filename)
        return response


class ServiceWarrantyPDFView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        service = get_object_or_404(
            _service_tenant_queryset(request).select_related('customer', 'technician__user').prefetch_related('items', 'payments'),
            pk=pk,
        )
        
        months = request.query_params.get('months')
        try:
            months = int(months) if months else 24
        except ValueError:
            months = 24
            
        warranty, created = WarrantyCertificate.objects.get_or_create(
            service=service,
            defaults={
                'tenant': _request_tenant(request),
                'warranty_months': months,
            }
        )
        
        if not created and request.query_params.get('months'):
            warranty.warranty_months = months
            warranty.save()

        pdf_buffer = generate_warranty_certificate_pdf(warranty)
        filename = f"Garanti_Belgesi_{service.receipt_number or str(service.id)[:8]}.pdf"
        response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
        disposition = request.query_params.get('disposition', 'attachment').lower()
        if disposition == 'inline':
            response['Content-Disposition'] = _build_inline_disposition(filename)
        else:
            response['Content-Disposition'] = _build_download_disposition(filename)
        return response


class ServiceFormEmailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        service = get_object_or_404(
            _service_tenant_queryset(request).select_related('customer', 'technician__user').prefetch_related('items', 'payments'),
            pk=pk,
        )

        recipient_email = request.data.get('email') or getattr(service.customer, 'email', None)
        if not recipient_email:
            return Response({'detail': 'Musteri e-posta adresi bulunamadi.'}, status=status.HTTP_400_BAD_REQUEST)

        subject = request.data.get('subject') or f"Servis Formu #{service.receipt_number}"
        message = request.data.get('message') or (
            f"Merhaba,\n\nServis formunuz ektedir.\n"
            f"Fis No: #{service.receipt_number}\n"
            f"Durum: {_status_label(service.service_status)}\n"
        )

        pdf_buffer = generate_service_form_pdf(service)
        email = EmailMessage(
            subject=subject,
            body=message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
            to=[recipient_email],
        )
        email.attach(
            _build_service_pdf_filename(service),
            pdf_buffer.getvalue(),
            'application/pdf',
        )
        email.send(fail_silently=False)

        return Response({'detail': f'Servis formu {recipient_email} adresine gonderildi.'}, status=status.HTTP_200_OK)


class ServiceWhatsAppStatusLinkView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        service = get_object_or_404(_service_tenant_queryset(request), pk=pk)
        next_status = request.data.get('status') or service.service_status
        whatsapp_url = _build_service_status_whatsapp_url(service, new_status=next_status, request=request, status_changed=False, scheduled_date=service.scheduled_date)
        return Response({'whatsapp_url': whatsapp_url}, status=status.HTTP_200_OK)


class PublicServiceListView(APIView):
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        access_token = request.query_params.get("access_token")
        token_service_id = resolve_public_service_token(access_token)
        if not token_service_id:
            return Response({"detail": "Erisim tokeni eksik veya gecersizdir."}, headers={"Cache-Control": "no-store, must-revalidate"}, status=status.HTTP_403_FORBIDDEN)

        token_service = Service.objects.select_related("customer").filter(id=token_service_id).first()
        if not token_service:
            return Response({"detail": "Token gecersiz servis kaydina ait."}, headers={"Cache-Control": "no-store, must-revalidate"}, status=status.HTTP_404_NOT_FOUND)
        token_tenant = getattr(getattr(token_service, "customer", None), "tenant", None)

        services = Service.objects.select_related('customer', 'technician', 'status') \
                            .prefetch_related('items', 'items__product', 'payments', 'timeline')
        services = services.filter(customer__tenant=token_tenant)
        services = services.filter(id=token_service_id)
        
        search = request.query_params.get('search')
        if search:
            services = services.filter(
                Q(receipt_number=search) |
                Q(customer_phone=search)
            )
        serializer = PublicServiceSerializer(services, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

class PublicServiceDetailView(APIView):
    permission_classes = [permissions.AllowAny]
    
    def get(self, request, pk):
        access_token = request.query_params.get("access_token")
        token_service_id = resolve_public_service_token(access_token)
        if not token_service_id:
            return Response({"detail": "Erisim tokeni eksik veya gecersizdir."}, headers={"Cache-Control": "no-store, must-revalidate"}, status=status.HTTP_403_FORBIDDEN)
        if str(pk) != str(token_service_id):
            return Response({"detail": "Erisim tokeni bu servis icin gecersiz."}, headers={"Cache-Control": "no-store, must-revalidate"}, status=status.HTTP_403_FORBIDDEN)

        token_service = Service.objects.select_related("customer").filter(id=token_service_id).first()
        if not token_service:
            return Response({"detail": "Token gecersiz servis kaydina ait."}, headers={"Cache-Control": "no-store, must-revalidate"}, status=status.HTTP_404_NOT_FOUND)
        token_tenant = getattr(getattr(token_service, "customer", None), "tenant", None)

        qs = Service.objects.select_related('customer', 'technician', 'status') \
                            .prefetch_related('items', 'items__product', 'payments', 'timeline')
        qs = qs.filter(customer__tenant=token_tenant)
        try:
            service = qs.get(id=pk)
        except Service.DoesNotExist:
            return Response({"detail": "Servis bulunamadı."}, headers={"Cache-Control": "no-store, must-revalidate"}, status=status.HTTP_404_NOT_FOUND)
        serializer = PublicServiceSerializer(service, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

class PublicServiceFormPDFView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk):
        access_token = request.query_params.get("access_token")
        token_service_id = resolve_public_service_token(access_token)
        if not token_service_id or str(pk) != str(token_service_id):
            return HttpResponse("Erişim reddedildi.", status=403)

        service = get_object_or_404(
            Service.objects.select_related('customer', 'technician__user').prefetch_related('items', 'payments'),
            pk=pk,
        )

        pdf_buffer = generate_service_form_pdf(service)
        filename = _build_service_pdf_filename(service)
        response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = _build_download_disposition(filename)
        return response
