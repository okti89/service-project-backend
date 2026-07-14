import uuid
import logging
from django.db import models, transaction

from django.contrib.auth.models import update_last_login
from rest_framework import permissions, status
from rest_framework.authtoken.models import Token
from rest_framework.views import APIView
from rest_framework.response import Response
from .serializers import (
    AdminLoginSerializer,
    UserCreateSerializer,
    CheckAuthSerializer,
    UserSerializer,
    RegisterSerializer,
    LoginSerializer,
    PasswordResetRequestSerializer,
    PasswordResetVerifySerializer,
    SetNewPasswordSerializer,
    ChangePasswordSerializer,
    UserDeviceSerializer
    )
from .models import User, UserDevice
logger = logging.getLogger(__name__)
from .utils import (
    send_admin_registration_email,
    send_approval_email,
    send_password_reset_email,
    send_rejected_email,
)
from notifications.services import create_notification
from technicians.services import ensure_technician_profile


#admin işlemleri
class AdminLoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = AdminLoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        token, _ = Token.objects.get_or_create(user=user)
        update_last_login(None, user)
        user_serializer = CheckAuthSerializer(user, context={"request": request})
        return Response({"token": token.key, "user": user_serializer.data}, status=status.HTTP_200_OK)


class UserListCreateAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        users = User.objects.filter(tenant=request.user.tenant)
        tab = (request.query_params.get("tab") or "").lower()
        include_inactive = request.query_params.get("include_inactive", "false").lower() == "true"
        query = (request.query_params.get("q") or "").strip()

        if tab == "deleted":
            users = users.filter(is_active=False)
        elif tab == "all":
            users = users.filter(is_active=True)
        elif not include_inactive:
            users = users.filter(is_active=True)

        if query:
            users = users.filter(
                models.Q(first_name__icontains=query)
                | models.Q(last_name__icontains=query)
                | models.Q(email__icontains=query)
                | models.Q(phone_number__icontains=query)
            )

        users = users.order_by("-date_joined")
        serializer = UserSerializer(users, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = UserCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class UserDetailAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def get_object(self, pk, tenant):
        try:
            return User.objects.get(pk=pk, tenant=tenant)
        except User.DoesNotExist:
            return None

    def get(self, request, pk):
        user = self.get_object(pk, request.user.tenant)
        if not user:
            return Response({"error": "Kullanıcı bulunamadı"}, status=status.HTTP_404_NOT_FOUND)
        serializer = UserSerializer(user, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, pk):
        user = self.get_object(pk, request.user.tenant)
        if not user:
            return Response({"error": "Kullanıcı bulunamadı"}, status=status.HTTP_404_NOT_FOUND)

        old_status = user.approval_status
        serializer = UserSerializer(user, data=request.data, partial=True, context={"request": request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer.save()
        if old_status != user.approval_status:
            if user.approval_status == "approved":
                user.is_active = True
                user.save(update_fields=["is_active"])
                ensure_technician_profile(user)
                create_notification(
                    user=user,
                    title="Hesabınız aktifleşti",
                    message="Hesabınız başarıyla aktifleşti. Giriş yapabilirsiniz.",
                )
            elif user.approval_status == "rejected":
                user.is_active = False
                user.save(update_fields=["is_active"])
                create_notification(
                    user=user,
                    title="Hesabınız reddedildi",
                    message="Hesabınız reddedildi. Yönetici ile iletişime geçin.",
                )

            try:
                if user.approval_status == "approved":
                    send_approval_email(user.email, user.get_full_name())
                elif user.approval_status == "rejected":
                    send_rejected_email(user.email, user.get_full_name())
            except Exception:
                logger.exception("Kullanici onay/redd e-postasi gonderilemedi. user_id=%s", user.id)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        """Kullanıcıyı pasife al (sadece is_active=False, approval_status değişmez)"""
        user = self.get_object(pk, request.user.tenant)
        if not user:
            return Response({"error": "Kullanıcı bulunamadı"}, status=status.HTTP_404_NOT_FOUND)

        user.is_active = False
        user.save(update_fields=["is_active"])
        create_notification(
            user=user,
            title="Hesabınız pasifleşti",
            message="Hesabınız yönetici tarafından pasife alındı.",
        )
        return Response({"message": "Kullanıcı pasife alındı"}, status=status.HTTP_200_OK)

    def put(self, request, pk):
        """Pasif kullanıcıyı aktif et (sadece is_active=True, approval_status değişmez)"""
        user = self.get_object(pk, request.user.tenant)
        if not user:
            return Response({"error": "Kullanıcı bulunamadı"}, status=status.HTTP_404_NOT_FOUND)

        user.is_active = True
        user.save(update_fields=["is_active"])
        create_notification(
            user=user,
            title="Hesabınız aktifleşti",
            message="Hesabınız yönetici tarafından tekrar aktif edildi. Giriş yapabilirsiniz.",
        )
        return Response({"message": "Kullanıcı aktif edildi"}, status=status.HTTP_200_OK)


class UserApprovalListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        status_param = request.query_params.get("status", "pending")
        if status_param not in ["pending", "approved", "rejected"]:
            status_param = "pending"

        users = User.objects.filter(approval_status=status_param, tenant=request.user.tenant)
        serializer = UserSerializer(users, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        user_id = request.data.get("user_id")
        new_status = request.data.get("status")


        try:
            user = User.objects.get(id=user_id, tenant=request.user.tenant)
        except User.DoesNotExist:
            return Response({"detail": "Kullanıcı bulunamadı"}, status=status.HTTP_404_NOT_FOUND)

        old_status = user.approval_status
        user.approval_status = new_status
        user.is_active = bool(new_status == "approved" or user.is_staff)
        user.save(update_fields=["approval_status", "is_active"])

        if old_status != "approved" and new_status == "approved":
            ensure_technician_profile(user)

            create_notification(
                user=user,
                title="Hesabınız onaylandı",
                message="Hesabınız yönetici tarafından onaylandı.",
                related_screen="Login",
            )

        elif old_status != "rejected" and new_status == "rejected":
            create_notification(
                user=user,
                title="Hesabınız reddedildi",
                message="Hesabınız yönetici tarafından reddedildi.",
            )

            try:
                send_rejected_email(user.email, user.get_full_name())
            except Exception:
                logger.exception("Reddedilen kullanici e-postasi gonderilemedi. user_id=%s", user.id)

        return Response(
            {"message": "Kullanıcı durumu güncellendi", "status": new_status, "user_id": user.id},
            status=status.HTTP_200_OK,
        )

#admin sonu

class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        user = serializer.save()

        admins = User.objects.filter(tenant=user.tenant).filter(
            models.Q(is_staff=True) | models.Q(user_type="admin"))
        
        for admin in admins:
            create_notification(
                user=admin,
                title="Yeni kullanıcı kaydı",
                message=f"{user.get_full_name()} sisteme kayıt oldu. Onayınızı bekliyor",
                related_screen="UserDetail",
                related_id=str(user.id),
            )

            try:
                send_admin_registration_email(admin, user.get_full_name(), user.email)
            except Exception:
                logger.exception("Admin mail error")

        token, _ = Token.objects.get_or_create(user=user)
        user_serializer = CheckAuthSerializer(user, context={"request": request})
        return Response({"token": token.key, "user": user_serializer.data},status=status.HTTP_201_CREATED)

class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        
        token, _ = Token.objects.get_or_create(user=user)
        update_last_login(None, user)
        user_serializer = CheckAuthSerializer(user, context={"request": request})
        return Response({"token": token.key, "user": user_serializer.data}, status=status.HTTP_200_OK)

class DeleteAccountView(APIView):
    """Permanently remove the authenticated user's account and personal records."""
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request):
        password = request.data.get("password", "")
        confirmation = str(request.data.get("confirmation", "")).strip().upper()
        user = request.user

        if confirmation != "SİL":
            return Response({"detail": "Onay için SİL yazmalısınız."}, status=status.HTTP_400_BAD_REQUEST)
        if not password or not user.check_password(password):
            return Response({"detail": "Parolanız doğrulanamadı."}, status=status.HTTP_400_BAD_REQUEST)

        # Device, token, location and technician records cascade. Historical service
        # records remain, while optional user references are detached with SET_NULL.
        with transaction.atomic():
            if user.avatar:
                user.avatar.delete(save=False)
            user.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)

class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            request.user.auth_token.delete()
        except Token.DoesNotExist:
            return Response({"detail":"Bir hata oluştu"},status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "Başarıyla çıkış yapıldı."},status=status.HTTP_200_OK)

class PasswordResetRequestView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.get_user()

        if not user:
            return Response(
                {"detail": "Bu email ile kayitli bir kullanici bulunamadi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        code = user.generate_password_reset_code()
        try:
            send_password_reset_email(user.email, code, user.get_full_name())
        except Exception as exc:
            logger.exception("Password reset mail send error for user=%s", user.email)
            return Response(
                {
                    "detail": "Parola sıfırlama kodu gönderilemedi. Lütfen e-posta ayarlarını kontrol edin.",
                    "error": str(exc),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {"detail": "Parola sıfırlama kodu email adresine gönderildi."},
            status=status.HTTP_200_OK,
        )


class PasswordResetVerifyView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({"detail": "Kod başarıyla doğrulandı."}, status=status.HTTP_200_OK)


class PasswordResetConfirmView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = SetNewPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Parolanız başarıyla sıfırlandı."}, status=status.HTTP_200_OK)


class PasswordChangeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Parolanız başarıyla değiştirildi."}, status=status.HTTP_200_OK)

class RegisterUserDeviceView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        token = request.data.get("token")
        device_id = request.data.get("device_id")
        device_name = request.data.get("device_name", "")
        platform = request.data.get("platform", "android")
        location_permission = bool(request.data.get("location_permission", False))
        notification_permission = bool(request.data.get("notification_permission", True))
        is_active = bool(request.data.get("is_active", True))

        if not token:
            return Response({"detail": "Token gerekli"}, status=status.HTTP_400_BAD_REQUEST)
        if not device_id:
            device_id = str(uuid.uuid4())

        user = request.user
        UserDevice.objects.update_or_create(
            expo_token=token,
            defaults={
                "user": user,
                "tenant": user.tenant,
                "device_name": device_name,
                "device_id": device_id,
                "platform": platform,
                "is_active": is_active,
                "location_permission": location_permission,
                "notification_permission": notification_permission,
            },
            
        )

        return Response(
            {"detail": "Token başarıyla kaydedildi", "device_id": device_id},
            status=status.HTTP_200_OK,
        )

class CheckAuthView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.approval_status == "pending":
            return Response(
                {"detail": "Hesabınız henüz onaylanmadı.", "account_status": "pending"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if user.approval_status == "rejected":
            return Response(
                {"detail": "Hesabınız reddedildi. Yöneticinizle iletişime geçin.", "account_status": "rejected"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not user.is_active:
            return Response(
                {"detail": "Hesabınız aktif değil. Yöneticinizle iletişime geçin.", "account_status": "deactivated"},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = CheckAuthSerializer(user, context={"request": request})
        update_last_login(None, user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        serializer = UserSerializer(
            request.user,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        response_serializer = CheckAuthSerializer(
            request.user,
            context={"request": request},
        )
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class AdminUserDeviceListView(APIView):
    """
    Admin tarafindan tenant icindeki tum kullanicilara ait cihazlari listeler.
    Sorgu parametreleri:
    - user_id: belirli bir kullanicinin cihazlari
    - platform: android | ios | web filtresi
    - is_active: true/false filtresi
    - q: cihaz adi/token icin arama
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        qs = UserDevice.objects.select_related("user", "tenant").filter(tenant=user.tenant)

        user_id = request.query_params.get("user_id")
        if user_id:
            qs = qs.filter(user_id=user_id)

        platform = request.query_params.get("platform")
        if platform in ("android", "ios", "web"):
            qs = qs.filter(platform=platform)

        is_active = request.query_params.get("is_active")
        if is_active is not None:
            if is_active.lower() in ("true", "1", "yes"):
                qs = qs.filter(is_active=True)
            elif is_active.lower() in ("false", "0", "no"):
                qs = qs.filter(is_active=False)

        q = request.query_params.get("q")
        if q:
            qs = qs.filter(
                models.Q(device_name__icontains=q)
                | models.Q(expo_token__icontains=q)
                | models.Q(user__first_name__icontains=q)
                | models.Q(user__last_name__icontains=q)
                | models.Q(user__email__icontains=q)
                | models.Q(user__phone_number__icontains=q)
            )

        qs = qs.order_by("-last_used_at")
        serializer = UserDeviceSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
