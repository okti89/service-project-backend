from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db.models import Q
from django.utils import timezone
from django.db import transaction
from django.conf import settings
from datetime import datetime, date, time, timedelta
import logging
from .permissions import IsNotificationManager

from accounts.models import User
from .models import Notification
from .serializers import NotificationSerializer
from .services import create_bulk_notification

from django.core.mail import send_mass_mail

logger = logging.getLogger(__name__)


class NotificationView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        qs = Notification.objects.filter(
            user=request.user,
            tenant=request.user.tenant
        )
        return Response(NotificationSerializer(qs, many=True).data)

    def patch(self, request, pk):
        try:
            obj = Notification.objects.get(
                pk=pk,
                user=request.user,
                tenant=request.user.tenant
            )
            obj.mark_as_read()
            return Response({"detail": "ok"})
        except Notification.DoesNotExist:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)

    def delete(self, request, pk):
        try:
            obj = Notification.objects.get(
                pk=pk,
                user=request.user,
                tenant=request.user.tenant
            )
            obj.delete()
            return Response({"detail": "deleted"})
        except Notification.DoesNotExist:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)

class AdminSendNotificationView(APIView):
    permission_classes = [IsNotificationManager]

    def post(self, request):
        title = request.data.get("title")
        message = request.data.get("message")
        user_ids = request.data.get("user_ids", [])
        send_to_all = request.data.get("send_to_all", False)
        send_push = request.data.get("send_push", True)
        send_email = request.data.get("send_email", False)

        if not title or not message:
            return Response({"detail": "zorunlu alanlar eksik"}, status=status.HTTP_400_BAD_REQUEST)

        users = User.objects.filter(
            is_active=True,
            tenant=request.user.tenant
        )

        if not send_to_all:
            users = users.filter(id__in=user_ids)

        if not users.exists():
            return Response({"detail": "kullanıcı yok"}, status=status.HTTP_404_NOT_FOUND)

        create_bulk_notification(
            users,
            title,
            message,
            send_push=send_push,
        )

        if send_email:
            def send_emails():
                mails = [
                    (title, message, settings.DEFAULT_FROM_EMAIL, [u.email])
                    for u in users if u.email
                ]
                send_mass_mail(mails, fail_silently=True)

            transaction.on_commit(send_emails)

        return Response({"detail": f"{users.count()} kullanıcıya gönderildi"})

class NewsFeedView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    # ---------- HELPERS ----------
    def _tenant(self):
        return getattr(self.request.user, "tenant", None)

    def _safe(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            logger.exception("NewsFeed ogeleri olusturulamadi: %s", exc)
            return []

    def _resolve_range(self):
        """Query params'a gore (start, end) datetime araligi dondurur."""
        period = (self.request.query_params.get("period") or "all").lower()
        tz = timezone.get_current_timezone()

        if period == "daily":
            date_str = self.request.query_params.get("date")
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else timezone.localdate()
            except (ValueError, TypeError):
                d = timezone.localdate()
            start = datetime.combine(d, time.min, tzinfo=tz)
            end = datetime.combine(d, time.max, tzinfo=tz)
            return start, end

        if period == "monthly":
            month_str = self.request.query_params.get("month")
            try:
                first = datetime.strptime(month_str, "%Y-%m").date() if month_str else timezone.localdate().replace(day=1)
            except (ValueError, TypeError):
                first = timezone.localdate().replace(day=1)
            if first.month == 12:
                next_first = first.replace(year=first.year + 1, month=1)
            else:
                next_first = first.replace(month=first.month + 1)
            start = datetime.combine(first, time.min, tzinfo=tz)
            end = datetime.combine(next_first, time.min, tzinfo=tz)
            return start, end

        if period == "yearly":
            year_str = self.request.query_params.get("year")
            try:
                year = int(year_str) if year_str else timezone.localdate().year
            except (ValueError, TypeError):
                year = timezone.localdate().year
            start = datetime(year, 1, 1, tzinfo=tz)
            end = datetime(year + 1, 1, 1, tzinfo=tz)
            return start, end

        return None, None

    # ---------- SERVICE ----------
    def _service_items(self, limit, start, end):
        from services.models import Service

        model_fields = {f.name for f in Service._meta.get_fields()}
        qs = Service.objects.all()
        if self._tenant() and "customer" in model_fields:
            qs = qs.filter(customer__tenant=self._tenant())

        if start and end and "created_at" in model_fields:
            qs = qs.filter(created_at__gte=start, created_at__lt=end)

        if "created_at" in model_fields:
            qs = qs.order_by("-created_at")
        qs = qs[:limit]

        items = []
        for x in qs:
            receipt = getattr(x, "receipt_number", None) or str(x.pk)
            items.append({
                "id": f"service:{x.pk}",
                "entity": "service",
                "title": "Yeni servis",
                "message": str(receipt),
                "created_at": getattr(x, "created_at", timezone.now()),
            })
        return items

    # ---------- TECHNICIAN ----------
    def _technician_items(self, limit, start, end):
        from technicians.models import Technician

        model_fields = {f.name for f in Technician._meta.get_fields()}
        qs = Technician.objects.select_related("user")
        if self._tenant() and "user" in model_fields:
            qs = qs.filter(user__tenant=self._tenant())

        if start and end and "created_at" in model_fields:
            qs = qs.filter(created_at__gte=start, created_at__lt=end)

        if "created_at" in model_fields:
            qs = qs.order_by("-created_at")
        qs = qs[:limit]

        items = []
        for x in qs:
            user = getattr(x, "user", None)
            label = ""
            if user is not None:
                label = (user.get_full_name() or user.email or "")
            items.append({
                "id": f"tech:{x.pk}",
                "entity": "technician",
                "title": "Yeni teknisyen",
                "message": label,
                "created_at": getattr(x, "created_at", timezone.now()),
            })
        return items

    # ---------- STOCK ----------
    def _stock_items(self, limit, start, end):
        try:
            from products.models import StockMovement
        except Exception as exc:
            logger.warning("StockMovement import edilemedi: %s", exc)
            return []

        model_fields = {f.name for f in StockMovement._meta.get_fields()}
        qs = StockMovement.objects.select_related("product", "technician").all()
        if self._tenant():
            qs = qs.filter(tenant=self._tenant())

        if start and end and "created_at" in model_fields:
            qs = qs.filter(created_at__gte=start, created_at__lt=end)

        qs = qs.order_by("-created_at")[:limit]

        type_labels = dict(getattr(StockMovement, "MOVEMENT_TYPES", []))
        items = []
        for x in qs:
            product_name = getattr(getattr(x, "product", None), "name", None) or "Ürün"
            type_label = type_labels.get(x.movement_type, x.movement_type)
            items.append({
                "id": f"stock:{x.pk}",
                "entity": "stock",
                "title": f"Stok {type_label.lower()}: {product_name}",
                "message": f"{x.quantity} adet",
                "created_at": getattr(x, "created_at", timezone.now()),
            })
        return items

    # ---------- PAYMENT ----------
    def _payment_items(self, limit, start, end):
        try:
            from services.models import ServicePayment
        except Exception as exc:
            logger.warning("ServicePayment import edilemedi: %s", exc)
            return []

        model_fields = {f.name for f in ServicePayment._meta.get_fields()}
        qs = ServicePayment.objects.select_related("service", "payment_method").all()
        if self._tenant():
            qs = qs.filter(tenant=self._tenant())

        if start and end and "created_at" in model_fields:
            qs = qs.filter(created_at__gte=start, created_at__lt=end)

        qs = qs.order_by("-created_at")[:limit]

        items = []
        for x in qs:
            service = getattr(x, "service", None)
            receipt = getattr(service, "receipt_number", None) or (str(service.pk) if service else "-")
            method = getattr(getattr(x, "payment_method", None), "name", None) or "Belirtilmedi"
            amount = str(getattr(x, "amount", "0"))
            items.append({
                "id": f"payment:{x.pk}",
                "entity": "payment",
                "title": f"Ödeme alındı: {receipt}",
                "message": f"{amount} TL • {method}",
                "created_at": getattr(x, "created_at", timezone.now()),
            })
        return items

    # ---------- SHIFT ----------
    def _shift_items(self, limit, start, end):
        try:
            from technicians.models import TechnicianShift
        except Exception as exc:
            logger.warning("TechnicianShift import edilemedi: %s", exc)
            return []

        model_fields = {f.name for f in TechnicianShift._meta.get_fields()}
        qs = TechnicianShift.objects.select_related("technician").all()
        if self._tenant():
            qs = qs.filter(tenant=self._tenant())

        if start and end and "date" in model_fields:
            qs = qs.filter(date__gte=start.date(), date__lt=end.date())

        qs = qs.order_by("-date")[:limit]

        items = []
        for x in qs:
            user = getattr(x, "technician", None)
            label = ""
            if user is not None:
                label = user.get_full_name() or user.email or ""
            shift_date = getattr(x, "date", None)
            items.append({
                "id": f"shift:{x.pk}",
                "entity": "shift",
                "title": "Mesai kaydı",
                "message": f"{label} • {shift_date}",
                "created_at": getattr(x, "created_at", timezone.now()) if hasattr(x, "created_at") else timezone.now(),
            })
        return items

    # ---------- PAYROLL ----------
    def _payroll_items(self, limit, start, end):
        try:
            from hr.models import Payroll
        except Exception as exc:
            logger.warning("Payroll modeli bulunamadi, atlaniyor: %s", exc)
            return []

        model_fields = {f.name for f in Payroll._meta.get_fields()}
        qs = Payroll.objects.all()
        if self._tenant() and "technician" in model_fields:
            qs = qs.filter(technician__user__tenant=self._tenant())

        if start and end and "created_at" in model_fields:
            qs = qs.filter(created_at__gte=start, created_at__lt=end)

        if "created_at" in model_fields:
            qs = qs.order_by("-created_at")
        qs = qs[:limit]

        items = []
        for x in qs:
            period = f"{getattr(x, 'period_start', '')} - {getattr(x, 'period_end', '')}"
            items.append({
                "id": f"payroll:{x.pk}",
                "entity": "payroll",
                "title": "Bordro",
                "message": period,
                "created_at": getattr(x, "created_at", timezone.now()),
            })
        return items

    # ---------- MAIN ----------
    def get(self, request):
        limit = int(request.query_params.get("limit", 100))
        limit = min(max(limit, 10), 300)

        entity_filter = request.query_params.get("entity")
        start, end = self._resolve_range()

        feed = []
        feed += self._safe(self._service_items, limit, start, end)
        feed += self._safe(self._technician_items, limit, start, end)
        feed += self._safe(self._stock_items, limit, start, end)
        feed += self._safe(self._payment_items, limit, start, end)
        feed += self._safe(self._shift_items, limit, start, end)
        feed += self._safe(self._payroll_items, limit, start, end)

        if entity_filter:
            feed = [item for item in feed if item["entity"] == entity_filter]

        feed.sort(key=lambda x: x["created_at"], reverse=True)

        return Response({
            "count": len(feed),
            "results": feed[:limit]
        })
