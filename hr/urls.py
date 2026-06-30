from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    TechnicianCompensationViewSet,
    PayrollViewSet,
    PayrollComponentViewSet,
    PayrollTemplateViewSet,
    TechnicianPayrollListView,
    TechnicianPayrollPDFView
)

app_name = "hr"

router = DefaultRouter()
router.register(r"technician-compensations", TechnicianCompensationViewSet, basename="technician-compensation")
router.register(r"payrolls", PayrollViewSet, basename="payroll")
router.register(r"payroll-components", PayrollComponentViewSet, basename="payroll-component")
router.register(r"payroll-templates", PayrollTemplateViewSet, basename="payroll-template")

urlpatterns = [
    path("", include(router.urls)),

    # Technician scoped endpoints (read-only client area)
    path("me/payrolls/", TechnicianPayrollListView.as_view(), name="me-payrolls"),
    path("me/payrolls/<uuid:pk>/pdf/", TechnicianPayrollPDFView.as_view(), name="me-payroll-pdf"),
]