from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CustomerViewSet, CustomerListView


router = DefaultRouter()
router.register(r"customers", CustomerViewSet, basename="customer")

urlpatterns = [
    path("customer-list/", CustomerListView.as_view(), name="customer-list"),
    path("", include(router.urls)),
]
