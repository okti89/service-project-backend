from django.urls import path
from .views import (
    AdminLoginView,UserListCreateAPIView,UserDetailAPIView,
    UserApprovalListView,RegisterView,LoginView,LogoutView,
    CheckAuthView,PasswordChangeView,PasswordResetRequestView,
    PasswordResetVerifyView,PasswordResetConfirmView,RegisterUserDeviceView,
    AdminUserDeviceListView)


urlpatterns = [
    path('admin/login/',AdminLoginView.as_view(),name='admin-login'),
    path('admin/users/',UserListCreateAPIView.as_view(),name='admin-users'),
    path('admin/users/<uuid:pk>/',UserDetailAPIView.as_view(),name='admin-user-detail'),
    path('admin/users/approval/',UserApprovalListView.as_view(),name='admin-user-approval'),
    # =========================
    # AUTH
    # =========================
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    path('auth/delete-account/', DeleteAccountView.as_view(), name='delete-account'),
    path('auth/change-password/', PasswordChangeView.as_view(), name='change-password'),
    path('auth/check/', CheckAuthView.as_view(), name='check-auth'),
    path('auth/me/', CheckAuthView.as_view(), name='auth-me'),

    # =========================
    # PASSWORD RESET
    # =========================

    path('auth/password/reset/request/', PasswordResetRequestView.as_view(), name='password-reset-request'),
    path('auth/password/reset/verify/', PasswordResetVerifyView.as_view(), name='password-reset-verify'),
    path('auth/password/reset/confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    # =========================
    # =========================
    # DEVICE REGISTER (push token registration, all authenticated users)
    # =========================
    path('devices/register/', RegisterUserDeviceView.as_view(), name='register-user-device'),
    # ADMIN - DEVICE MANAGEMENT
    # =========================
    path('admin/devices/', AdminUserDeviceListView.as_view(), name='admin-user-device-list'),

    
]