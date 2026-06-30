from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AppFeedbackViewSet

router = DefaultRouter()
router.register(r'feedbacks', AppFeedbackViewSet, basename='feedback')

urlpatterns = [
    path('', include(router.urls)),
]