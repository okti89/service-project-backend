from django.urls import path

from .views import (
    NotificationView,
    AdminSendNotificationView,
    NewsFeedView,
)

urlpatterns = [
    # Notifications
    path("notifications/", NotificationView.as_view(), name="notifications-list"),
    path("notifications/<int:pk>/", NotificationView.as_view(), name="notifications-detail"),

    # Admin push/email send
    path("admin/notifications/send/", AdminSendNotificationView.as_view(), name="admin-send-notification"),


    # Feed
    path("feed/", NewsFeedView.as_view(), name="news-feed"),
]