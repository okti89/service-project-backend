from django.urls import path
from .views import (
    GeneralPerformanceAPIView,
    TechnicianPerformanceAPIView,
    TechnicianDetailPerformanceAPIView,
    DashboardStatsAPIView,
    DailyServiceListPDFView,
    DailySummaryPDFView,
    MyPerformanceAPIView,
    OverdueReceivablesAPIView,
)

urlpatterns = [
    path('dashboard/', DashboardStatsAPIView.as_view(), name='report-dashboard'),
    path('daily-summary/pdf/', DailySummaryPDFView.as_view(), name='report-daily-summary-pdf'),
    path('daily-service-list/pdf/', DailyServiceListPDFView.as_view(), name='report-daily-service-list-pdf'),
    path('general/', GeneralPerformanceAPIView.as_view(), name='report-general'),
    path('technician/', TechnicianPerformanceAPIView.as_view(), name='report-technician'),
    path('technician/unassigned/', TechnicianDetailPerformanceAPIView.as_view(), {'pk': 'unassigned'}, name='report-technician-unassigned-detail'),
    path('technician/<uuid:pk>/', TechnicianDetailPerformanceAPIView.as_view(), name='report-technician-detail'),
    path('my-performance/', MyPerformanceAPIView.as_view(), name='my-performance'),
    path('overdue-receivables/', OverdueReceivablesAPIView.as_view(), name='report-overdue-receivables'),
]
