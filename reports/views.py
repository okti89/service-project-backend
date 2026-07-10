from datetime import datetime, timedelta
from decimal import Decimal

# Reports views configuration
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.http import FileResponse
from django.utils import timezone as tz
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounting.models import Transaction
from customers.models import Customer
from products.models import Product
from services.models import Service, ServicePayment
from technicians.models import Technician

from .serializers import GeneralPerformanceSerializer, TechnicianPerformanceSerializer
from .utils import generate_general_performance_pdf, generate_technician_performance_pdf


SERVICE_STATUS_COLORS = {
    'new': '#6B7280',
    'assigned': '#2563EB',
    'in_progress': '#F59E0B',
    'completed': '#16A34A',
    'cancelled': '#DC2626',
}


class IsAdminLikeUser(permissions.BasePermission):
    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        return bool(user.is_superuser or user.is_staff or getattr(user, 'user_type', '') == 'admin')


def reversal_transaction_filter():
    return (
        Q(receipt_number__icontains=':REV:')
        | Q(description__icontains='ters kayit')
        | Q(description__icontains='ters kayıt')
        | Q(description__icontains='iptal')
    )

def get_request_tenant(request):
    return getattr(getattr(request, 'user', None), 'tenant', None)


def parse_date_filters(request):
    params = getattr(request, 'query_params', None) or getattr(request, 'GET', {})
    year = params.get('year')
    month = params.get('month')

    start_date = None
    end_date = None

    if year:
        try:
            year = int(year)
            if month:
                month = int(month)
                start_date = tz.make_aware(datetime(year, month, 1))
                if month == 12:
                    end_date = tz.make_aware(datetime(year + 1, 1, 1))
                else:
                    end_date = tz.make_aware(datetime(year, month + 1, 1))
            else:
                start_date = tz.make_aware(datetime(year, 1, 1))
                end_date = tz.make_aware(datetime(year + 1, 1, 1))
        except (ValueError, TypeError):
            return None, None

    return start_date, end_date


def calculate_outstanding_receivables(service_queryset):
    """Muhasebe sayfasindaki `Tahsil Edilmemis` (overdue receivables) ile birebir ayni hesap.

    Sadece zamani gecmis (scheduled_date < now) ve iptal edilmemis servislerin
    odenmemis (items total - payments paid) kalani toplanir.
    """
    outstanding = Decimal('0.00')
    overdue_count = 0
    now = tz.now()
    overdue_services = (
        service_queryset
        .filter(scheduled_date__lt=now)
        .exclude(status__code='cancelled')
        .prefetch_related('items', 'payments')
    )
    for service in overdue_services:
        service_total = sum(Decimal(str(item.total_price or 0)) for item in service.items.all())
        paid_total = sum(Decimal(str(payment.amount or 0)) for payment in service.payments.all())
        remaining = service_total - paid_total
        if remaining > 0:
            outstanding += remaining
            overdue_count += 1
    return outstanding, overdue_count


def apply_period_to_payments(payment_qs, start_date=None, end_date=None):
    if start_date and end_date:
        return payment_qs.filter(created_at__gte=start_date, created_at__lt=end_date)
    return payment_qs


def calculate_technician_revenue(technician, start_date=None, end_date=None, tenant=None):
    # Ciro, servis durumundan bağımsız olarak alınmış gerçek tahsilattır.
    payment_qs = ServicePayment.objects.exclude(service__status__code='cancelled')
    if tenant:
        payment_qs = payment_qs.filter(service__customer__tenant=tenant)
    if technician is None:
        payment_qs = payment_qs.filter(service__technician__isnull=True)
    else:
        payment_qs = payment_qs.filter(service__technician=technician)
    payment_qs = apply_period_to_payments(payment_qs, start_date, end_date)
    return payment_qs.aggregate(total=Sum('amount'))['total'] or 0


def serialize_service_for_report(service, start_date=None, end_date=None):
    total_payment_qs = apply_period_to_payments(ServicePayment.objects.filter(service=service), start_date, end_date)
    total_payment = total_payment_qs.aggregate(total=Sum('amount'))['total'] or 0
    return {
        'id': service.id,
        'receipt_number': service.receipt_number,
        'customer_full_name': service.customer_full_name,
        'customer_phone': service.customer_phone,
        'fault_description': service.fault_description,
        'device_type': str(service.device_type) if service.device_type else None,
        'device_brand': str(service.device_brand) if service.device_brand else None,
        'device_model': str(service.device_model) if service.device_model else None,
        'service_status': service.service_status,
        'is_completed': service.service_status == 'completed',
        'scheduled_date': service.scheduled_date,
        'completed_at': service.updated_at if service.service_status == 'completed' else None,
        'total_payment': total_payment,
    }


class DashboardStatsAPIView(APIView):
    permission_classes = [IsAdminLikeUser]

    def get(self, request):
        tenant = get_request_tenant(request)
        today = tz.now()
        params = getattr(request, 'query_params', None) or getattr(request, 'GET', {})
        selected_year = params.get('year')
        current_year = int(selected_year) if str(selected_year or '').isdigit() else today.year

        start_date, end_date = parse_date_filters(request)

        income_qs = Transaction.objects.filter(transaction_type='income', tenant=tenant)
        expense_qs = Transaction.objects.filter(transaction_type='expense', tenant=tenant)
        reversal_qs = expense_qs.filter(reversal_transaction_filter())
        operational_expense_qs = expense_qs.exclude(reversal_transaction_filter())
        service_qs = Service.objects.filter(customer__tenant=tenant)

        if start_date and end_date:
            income_qs = income_qs.filter(date__gte=start_date, date__lt=end_date)
            reversal_qs = reversal_qs.filter(date__gte=start_date, date__lt=end_date)
            operational_expense_qs = operational_expense_qs.filter(date__gte=start_date, date__lt=end_date)
            service_qs = service_qs.filter(created_at__gte=start_date, created_at__lt=end_date)

        gross_revenue = income_qs.aggregate(total=Sum('amount'))['total'] or 0
        total_reversal = reversal_qs.aggregate(total=Sum('amount'))['total'] or 0
        outstanding_receivables, total_overdue_receivables = calculate_outstanding_receivables(service_qs)
        total_expenses = operational_expense_qs.aggregate(total=Sum('amount'))['total'] or 0

        # Ciro sadece tahsil edilen gelir (muhasebe ile birebir).
        total_revenue = gross_revenue
        net_revenue = total_revenue - total_reversal
        net_profit = net_revenue - total_expenses

        start_of_month = tz.make_aware(datetime(current_year, today.month, 1))
        last_month_date = start_of_month - timedelta(days=1)
        start_of_last_month = tz.make_aware(datetime(last_month_date.year, last_month_date.month, 1))

        current_month_income = income_qs.filter(date__gte=start_of_month).aggregate(total=Sum('amount'))['total'] or 0
        current_month_reversal = reversal_qs.filter(date__gte=start_of_month).aggregate(total=Sum('amount'))['total'] or 0

        current_month_total = current_month_income - current_month_reversal

        last_month_income = income_qs.filter(date__gte=start_of_last_month, date__lt=start_of_month).aggregate(total=Sum('amount'))['total'] or 0
        last_month_reversal = reversal_qs.filter(date__gte=start_of_last_month, date__lt=start_of_month).aggregate(total=Sum('amount'))['total'] or 0
        last_month_total = last_month_income - last_month_reversal

        revenue_growth = 0
        if last_month_total > 0:
            revenue_growth = ((current_month_total - last_month_total) / last_month_total) * 100
        elif current_month_total > 0:
            revenue_growth = 100

        monthly_income = (
            Transaction.objects.filter(transaction_type='income', date__year=current_year, tenant=tenant)
            .annotate(month=TruncMonth('date'))
            .values('month')
            .annotate(total=Sum('amount'))
            .order_by('month')
        )

        income_map = {entry['month'].month: entry['total'] for entry in monthly_income}

        months_tr = ['Oca', 'Sub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Agu', 'Eyl', 'Eki', 'Kas', 'Ara']
        monthly_revenue_chart = []
        for i in range(1, 13):
            monthly_total = income_map.get(i) or 0
            monthly_revenue_chart.append({'name': months_tr[i - 1], 'total': monthly_total})

        active_services_count = Service.objects.filter(customer__tenant=tenant).exclude(status__code__in=['completed', 'cancelled']).count()
        pending_services_count = Service.objects.filter(customer__tenant=tenant, status__code__in=['new', 'assigned', 'in_progress', 'postponed']).count()
        completed_services_count = Service.objects.filter(customer__tenant=tenant, status__code='completed').count()
        cancelled_services_count = Service.objects.filter(customer__tenant=tenant, status__code='cancelled').count()
        total_services_count = Service.objects.filter(customer__tenant=tenant).count()
        total_customers_count = Customer.objects.filter(tenant=tenant).count()
        technicians_count = Technician.objects.filter(user__is_active=True, user__tenant=tenant).count()
        critical_stock_count = Product.objects.filter(stock_quantity__lte=5, is_active=True, tenant=tenant).count()

        recent_services = Service.objects.filter(customer__tenant=tenant).select_related('customer', 'technician__user').order_by('-created_at')[:5]
        recent_activity = []
        for service in recent_services:
            status_code = service.service_status or 'new'
            recent_activity.append(
                {
                    'id': service.id,
                    'type': 'service',
                    'title': f"Yeni Servis: #{service.receipt_number}",
                    'description': f"{service.customer_full_name or 'Musteri'} - {str(service.device_model) if service.device_model else 'Cihaz'}",
                    'time': service.created_at,
                    'status': status_code,
                    'status_color': SERVICE_STATUS_COLORS.get(status_code, '#6B7280'),
                }
            )

        return Response(
            {
                'gross_revenue': gross_revenue,
                'outstanding_receivables': outstanding_receivables,
                'total_overdue_receivables': total_overdue_receivables,
                'total_reversal': total_reversal,
                'total_revenue': total_revenue,
                'net_revenue': net_revenue,
                'total_expenses': total_expenses,
                'net_profit': net_profit,
                'revenue_growth': round(revenue_growth, 1),
                'monthly_revenue': monthly_revenue_chart,
                'active_services_count': active_services_count,
                'total_pending_services': pending_services_count,
                'total_completed_services': completed_services_count,
                'total_cancelled_services': cancelled_services_count,
                'total_services': total_services_count,
                'total_customers': total_customers_count,
                'technicians_count': technicians_count,
                'critical_stock_count': critical_stock_count,
                'recent_activity': recent_activity,
            },
            status=status.HTTP_200_OK,
        )


class GeneralPerformanceAPIView(APIView):
    permission_classes = [IsAdminLikeUser]

    def get_performance_data(self, tenant=None, start_date=None, end_date=None):
        income_qs = Transaction.objects.filter(transaction_type='income', tenant=tenant)
        expense_qs = Transaction.objects.filter(transaction_type='expense', tenant=tenant)
        reversal_qs = expense_qs.filter(reversal_transaction_filter())
        operational_expense_qs = expense_qs.exclude(reversal_transaction_filter())
        service_qs = Service.objects.filter(customer__tenant=tenant)

        if start_date and end_date:
            income_qs = income_qs.filter(date__gte=start_date, date__lt=end_date)
            reversal_qs = reversal_qs.filter(date__gte=start_date, date__lt=end_date)
            operational_expense_qs = operational_expense_qs.filter(date__gte=start_date, date__lt=end_date)
            service_qs = service_qs.filter(created_at__gte=start_date, created_at__lt=end_date)

        gross_revenue = income_qs.aggregate(total=Sum('amount'))['total'] or 0
        outstanding_receivables, total_overdue_receivables = calculate_outstanding_receivables(service_qs)
        total_reversal = reversal_qs.aggregate(total=Sum('amount'))['total'] or 0
        total_expenses = operational_expense_qs.aggregate(total=Sum('amount'))['total'] or 0

        # Ciro sadece tahsil edilen gelir (muhasebe ile birebir).
        total_revenue = gross_revenue
        net_revenue = total_revenue - total_reversal
        total_profit = net_revenue - total_expenses

        total_services = service_qs.count()
        total_customers = service_qs.values('customer').distinct().count()
        total_technicians = service_qs.exclude(technician__isnull=True).values('technician').distinct().count()
        total_completed_services = service_qs.filter(status__code='completed').count()
        total_pending_services = service_qs.exclude(status__code__in=['completed', 'cancelled']).count()
        total_cancelled_services = service_qs.filter(status__code='cancelled').count()

        completed_pct = (total_completed_services / total_services * 100) if total_services > 0 else 0
        pending_pct = (total_pending_services / total_services * 100) if total_services > 0 else 0
        cancelled_pct = (total_cancelled_services / total_services * 100) if total_services > 0 else 0

        return {
            'gross_revenue': gross_revenue,
            'outstanding_receivables': outstanding_receivables,
            'total_overdue_receivables': total_overdue_receivables,
            'total_reversal': total_reversal,
            'total_revenue': total_revenue,
            'net_revenue': net_revenue,
            'total_expenses': total_expenses,
            'total_profit': total_profit,
            'total_services': total_services,
            'total_customers': total_customers,
            'total_technicians': total_technicians,
            'total_completed_services': total_completed_services,
            'total_pending_services': total_pending_services,
            'total_cancelled_services': total_cancelled_services,
            'total_completed_services_percentage': completed_pct,
            'total_pending_services_percentage': pending_pct,
            'total_cancelled_services_percentage': cancelled_pct,
        }

    def get(self, request):
        start_date, end_date = parse_date_filters(request)
        tenant = get_request_tenant(request)
        data = self.get_performance_data(tenant, start_date, end_date)
        params = getattr(request, 'query_params', None) or getattr(request, 'GET', {})

        if params.get('export') == 'pdf':
            pdf_buffer = generate_general_performance_pdf(data)
            now = tz.now().strftime('%d_%m_%Y_%H%M')
            filename = f"genel_sistem_performans_raporu_{now}.pdf"
            return FileResponse(pdf_buffer, as_attachment=True, filename=filename)

        serializer = GeneralPerformanceSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class TechnicianPerformanceAPIView(APIView):
    permission_classes = [IsAdminLikeUser]

    def get_performance_data(self, tenant=None, start_date=None, end_date=None):
        technicians = Technician.objects.select_related('user').filter(user__tenant=tenant)
        data = []

        for tech in technicians:
            completed_qs = Service.objects.filter(technician=tech, status__code='completed', customer__tenant=tenant)
            if start_date and end_date:
                completed_qs = completed_qs.filter(created_at__gte=start_date, created_at__lt=end_date)

            completed_count = completed_qs.count()
            revenue = calculate_technician_revenue(tech, start_date, end_date, tenant)

            data.append(
                {
                    'technician_id': tech.id,
                    'technician_name': tech.user.get_full_name() or tech.user.email,
                    'completed_services_count': completed_count,
                    'total_revenue_generated': revenue,
                }
            )

        unassigned_completed_qs = Service.objects.filter(technician__isnull=True, status__code='completed', customer__tenant=tenant)
        if start_date and end_date:
            unassigned_completed_qs = unassigned_completed_qs.filter(created_at__gte=start_date, created_at__lt=end_date)

        unassigned_revenue = calculate_technician_revenue(None, start_date, end_date, tenant)
        unassigned_completed_count = unassigned_completed_qs.count()
        if unassigned_revenue or unassigned_completed_count:
            data.append(
                {
                    'technician_id': None,
                    'technician_name': 'Atanmamış Servisler',
                    'completed_services_count': unassigned_completed_count,
                    'total_revenue_generated': unassigned_revenue,
                }
            )

        return data

    def get(self, request):
        start_date, end_date = parse_date_filters(request)
        tenant = get_request_tenant(request)
        data = self.get_performance_data(tenant, start_date, end_date)
        params = getattr(request, 'query_params', None) or getattr(request, 'GET', {})

        if params.get('export') == 'pdf':
            pdf_buffer = generate_technician_performance_pdf(data)
            now = tz.now().strftime('%d_%m_%Y_%H%M')
            filename = f"teknisyen_performans_raporu_{now}.pdf"
            return FileResponse(pdf_buffer, as_attachment=True, filename=filename)

        serializer = TechnicianPerformanceSerializer(data, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class TechnicianDetailPerformanceAPIView(APIView):
    permission_classes = [IsAdminLikeUser]

    def get(self, request, pk):
        tenant = get_request_tenant(request)
        is_unassigned = str(pk) == 'unassigned'
        tech = None if is_unassigned else Technician.objects.select_related('user').filter(pk=pk, user__tenant=tenant).first()
        if not is_unassigned and not tech:
            return Response({'detail': 'Teknisyen bulunamadi.'}, status=status.HTTP_404_NOT_FOUND)

        start_date, end_date = parse_date_filters(request)

        if is_unassigned:
            service_qs = Service.objects.filter(technician__isnull=True, customer__tenant=tenant).select_related('customer', 'technician__user')
        else:
            service_qs = Service.objects.filter(technician=tech, customer__tenant=tenant).select_related('customer', 'technician__user')
        if start_date and end_date:
            service_qs = service_qs.filter(
                Q(created_at__gte=start_date, created_at__lt=end_date)
                | Q(payments__created_at__gte=start_date, payments__created_at__lt=end_date)
            ).distinct()

        completed_qs = service_qs.filter(status__code='completed')
        pending_qs = service_qs.exclude(status__code__in=['completed', 'cancelled'])

        completed_count = completed_qs.count()
        pending_count = pending_qs.count()
        revenue = calculate_technician_revenue(tech, start_date, end_date, tenant)

        services_data = [
            serialize_service_for_report(service, start_date, end_date)
            for service in service_qs.order_by('-scheduled_date')[:50]
        ]

        return Response(
            {
                'technician_id': None if is_unassigned else tech.id,
                'technician_name': 'Atanmamış Servisler' if is_unassigned else (tech.user.get_full_name() or tech.user.email),
                'completed_services_count': completed_count,
                'pending_services_count': pending_count,
                'total_revenue_generated': revenue,
                'services': services_data,
            },
            status=status.HTTP_200_OK,
        )


class MyPerformanceAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        tenant = get_request_tenant(request)
        tech = Technician.objects.filter(user=request.user, user__tenant=tenant).first()
        if not tech:
            tech = Technician.objects.filter(user=request.user).first()
        if not tech:
            return Response(
                {
                    'technician_id': None,
                    'technician_name': request.user.get_full_name() or request.user.email,
                    'completed_services_count': 0,
                    'pending_services_count': 0,
                    'total_revenue_generated': 0,
                    'services': [],
                },
                status=status.HTTP_200_OK,
            )

        start_date, end_date = parse_date_filters(request)

        service_qs = Service.objects.filter(technician=tech, customer__tenant=tenant).select_related('customer', 'technician__user')
        if start_date and end_date:
            service_qs = service_qs.filter(
                Q(created_at__gte=start_date, created_at__lt=end_date)
                | Q(payments__created_at__gte=start_date, payments__created_at__lt=end_date)
            ).distinct()

        completed_qs = service_qs.filter(status__code='completed')
        pending_qs = service_qs.exclude(status__code__in=['completed', 'cancelled'])

        completed_count = completed_qs.count()
        pending_count = pending_qs.count()
        revenue = calculate_technician_revenue(tech, start_date, end_date, tenant)

        services_data = [
            serialize_service_for_report(service, start_date, end_date)
            for service in service_qs.order_by('-scheduled_date')[:50]
        ]

        return Response(
            {
                'technician_id': tech.id,
                'technician_name': tech.user.get_full_name() or tech.user.email,
                'completed_services_count': completed_count,
                'pending_services_count': pending_count,
                'total_revenue_generated': revenue,
                'services': services_data,
            },
            status=status.HTTP_200_OK,
        )


class OverdueReceivablesAPIView(APIView):
    permission_classes = [IsAdminLikeUser]

    def get(self, request):
        tenant = get_request_tenant(request)
        now = tz.now()
        limit_raw = (request.query_params.get('limit') or '100').strip()
        limit = 100
        if str(limit_raw).isdigit():
            limit = max(1, min(int(limit_raw), 500))

        service_qs = (
            Service.objects.filter(customer__tenant=tenant, scheduled_date__lt=now)
            .exclude(status__code='cancelled')
            .select_related('customer', 'status', 'technician__user')
            .prefetch_related('items', 'payments')
            .order_by('scheduled_date')
        )

        rows = []
        for service in service_qs:
            service_total = sum(Decimal(str(item.total_price or 0)) for item in service.items.all())
            paid_total = sum(Decimal(str(payment.amount or 0)) for payment in service.payments.all())
            remaining = service_total - paid_total
            if remaining <= 0:
                continue
            rows.append(
                {
                    'service_id': str(service.id),
                    'receipt_number': service.receipt_number,
                    'customer_id': str(service.customer_id) if service.customer_id else None,
                    'customer_full_name': service.customer_full_name or getattr(service.customer, 'full_name', None),
                    'customer_phone': service.customer_phone,
                    'scheduled_date': service.scheduled_date,
                    'service_status': service.service_status,
                    'technician_name': (
                        service.technician.user.get_full_name()
                        if getattr(getattr(service, 'technician', None), 'user', None)
                        else None
                    ),
                    'total_amount': service_total,
                    'paid_amount': paid_total,
                    'remaining_amount': remaining,
                }
            )
            if len(rows) >= limit:
                break

        return Response(
            {
                'count': len(rows),
                'results': rows,
            },
            status=status.HTTP_200_OK,
        )
