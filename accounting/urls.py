from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AccountViewSet,
    TransactionCategoryViewSet,
    TransactionViewSet,
)


router = DefaultRouter()

router.register(
    r'accounts',
    AccountViewSet,
    basename='account'
)

router.register(
    r'transaction-categories',
    TransactionCategoryViewSet,
    basename='transaction-category'
)

router.register(
    r'transactions',
    TransactionViewSet,
    basename='transaction'
)


urlpatterns = [
    path('', include(router.urls)),
]
