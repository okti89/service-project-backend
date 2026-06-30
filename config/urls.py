from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    CompanyConfigViewSet,
    WorkingHourViewSet,
    HolidayExceptionViewSet,
    PublicCompanyConfigView,
)

router = DefaultRouter()
router.register(r"company-configs", CompanyConfigViewSet, basename="company-configs")
router.register(r"working-hours", WorkingHourViewSet, basename="working-hours")
router.register(r"holiday-exceptions", HolidayExceptionViewSet, basename="holiday-exceptions")

urlpatterns = [
    # 🌐 Public endpoint
    path("public/company/", PublicCompanyConfigView.as_view(), name="public-company"),
    # API endpoints from router
    path("", include(router.urls)),
]