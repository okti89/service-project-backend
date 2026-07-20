from notifications.models import Notification
from rest_framework import serializers
from .models import User, UserDevice
from tenants.utils import resolve_tenant_from_request
from config.models import CompanyConfig
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
import secrets



# =========================
# USER FINDER (optimized)
# =========================

def find_user_by_email(email, tenant=None):
    value = (email or "").strip()
    if not value:
        return None

    return (
        User.objects
        .filter(email__iexact=value)
        .filter(tenant=tenant) if tenant else User.objects
        .filter(email__iexact=value)
    ).first()

# =========================
# ADMIN LOGIN (unchanged logic)
# =========================
class AdminLoginSerializer(serializers.Serializer):
    email = serializers.CharField()
    password = serializers.CharField(write_only=True)

    default_error_messages = {
        "invalid_credentials": "Email veya şifre hatalı.",
        "not_admin": "Bu hesap yönetici değil.",
        "inactive": "Hesap aktif değil.",
        "pending": "Hesap onay bekliyor.",
    }

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")

        tenant = resolve_tenant_from_request(self.context.get("request"))
        user = find_user_by_email(email, tenant=tenant)

        if not user or not user.check_password(password):
            raise serializers.ValidationError({"detail": self.error_messages["invalid_credentials"]})

        if user.user_type != "admin":
            raise serializers.ValidationError({"detail": self.error_messages["not_admin"]})

        if user.approval_status != "approved":
            raise serializers.ValidationError({"detail": self.error_messages["pending"]})

        if not user.is_active:
            raise serializers.ValidationError({"detail": self.error_messages["inactive"]})

        attrs["user"] = user
        return attrs

# =========================
# USER CREATE
# =========================

class UserCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("email", "password", "first_name", "last_name", "phone_number", "user_type")
        extra_kwargs = {"password": {"write_only": True}}

    def validate(self, attrs):
        request = self.context.get("request")
        tenant = resolve_tenant_from_request(request)

        if tenant and not tenant.subscription_info()['is_active']:
            raise serializers.ValidationError({"detail": "Tenant subscription has expired. New user registration is unavailable."})

        phone = (attrs.get("phone_number") or "").strip()

        if tenant and phone:
            if User.objects.filter(tenant=tenant, phone_number=phone).exists():
                raise serializers.ValidationError(
                    {"phone_number": "Bu telefon numarası bu firma için zaten kayıtlı."}
                )

        if tenant:
            config = CompanyConfig.objects.filter(tenant=tenant).first()
            max_users = int(getattr(config, "max_users", 0) or 0)

            if max_users > 0:
                if User.objects.filter(tenant=tenant, is_active=True).count() >= max_users:
                    raise serializers.ValidationError(
                        "Sisteme kayıtlı maksimum kullanıcı sınırına ulaşıldı."
                    )

        return attrs

    def create(self, validated_data):
        tenant = resolve_tenant_from_request(self.context.get("request"))
        if tenant:
            validated_data["tenant"] = tenant
        return User.objects.create_user(**validated_data)


# =========================
# USER SERIALIZER
# =========================

class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="get_full_name", read_only=True)
    approval_status_display = serializers.CharField(source="get_approval_status_display", read_only=True)
    user_type_display = serializers.CharField(source="get_user_type_display", read_only=True)
    tenant_code = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "phone_number",
            "first_name",
            "last_name",
            "full_name",
            "avatar",
            "avatar_url",
            "is_staff",
            "is_platform_admin",
            "is_active",
            "user_type",
            "user_type_display",
            "approval_status",
            "approval_status_display",
            "date_joined",
            "tenant_code",
        )
        read_only_fields = ("id", "is_staff", "is_superuser", "is_platform_admin", "date_joined")

    def get_tenant_code(self, obj):
        tenant = getattr(obj, 'tenant', None)
        return getattr(tenant, 'code', None) if tenant else None

    def get_avatar(self, obj):
        if obj.avatar:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.avatar.url)
            return obj.avatar.url
        return None

    def get_avatar_url(self, obj):
        return self.get_avatar(obj)

# =========================
# REGISTER
# =========================
class RegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("email", "password", "first_name", "last_name", "phone_number", "user_type")
        extra_kwargs = {"password": {"write_only": True}}

    def validate(self, attrs):
        request = self.context.get("request")
        tenant = resolve_tenant_from_request(request)

        if not tenant:
            raise serializers.ValidationError({"detail": "Geçersiz firma kodu."})


        if not tenant.subscription_info()['is_active']:
            raise serializers.ValidationError({"detail": "Tenant subscription has expired. New user registration is unavailable."})

        phone = (attrs.get("phone_number") or "").strip()

        if phone and User.objects.filter(tenant=tenant, phone_number=phone).exists():
            raise serializers.ValidationError(
                {"phone_number": "Bu telefon numarası zaten kayıtlı."}
            )

        config = CompanyConfig.objects.filter(tenant=tenant).first()
        max_users = int(getattr(config, "max_users", 0) or 0)

        if max_users > 0:
            if User.objects.filter(tenant=tenant, is_active=True).count() >= max_users:
                raise serializers.ValidationError("Maksimum kullanıcı sayısına ulaştınız.Lütfen ek limit için yönetici ile iletişime geçiniz")

        return attrs

    def create(self, validated_data):
        validated_data["tenant"] = resolve_tenant_from_request(self.context.get("request"))
        return User.objects.create_user(**validated_data)

# =========================
# LOGIN
# =========================

class LoginSerializer(serializers.Serializer):
    email = serializers.CharField()
    password = serializers.CharField(write_only=True)
    default_error_messages = {
        "invalid_credentials": "Email veya şifre hatalıdır. Lütfen bilgilerinizi kontrol edin.",
        "inactive": "Hesabınız aktif değil. Lütfen yönetici ile iletişime geçin.",
    }

    def validate(self, attrs):
        tenant = resolve_tenant_from_request(self.context.get("request"))
        user = find_user_by_email(attrs["email"], tenant=tenant)
        if not user:
            user = find_user_by_email(attrs["email"], tenant=None)

        if not user or not user.check_password(attrs["password"]):
            raise serializers.ValidationError({"detail": self.error_messages["invalid_credentials"]})

        if not user.is_active:
            raise serializers.ValidationError({"detail": self.error_messages["inactive"]})

        attrs["user"] = user
        return attrs

# =========================
# CHANGE PASSWORD
# =========================

class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField(min_length=8)

    def validate(self, attrs):
        user = self.context["request"].user

        if not user.check_password(attrs["old_password"]):
            raise serializers.ValidationError({"old_password": "Eski şifre hatalı."})

        if attrs["old_password"] == attrs["new_password"]:
            raise serializers.ValidationError({"new_password": "Şifre aynı olamaz."})

        try:
            validate_password(attrs["new_password"], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)})

        attrs["user"] = user
        return attrs

    def save(self):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user

class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def get_user(self):
        tenant = resolve_tenant_from_request(self.context.get("request"))
        email = self.validated_data.get("email")
        user = find_user_by_email(email, tenant=tenant)
        if user:
            return user
        # Fallback: stale/incorrect tenant code should not block password reset lookup.
        return find_user_by_email(email, tenant=None)

class PasswordResetVerifySerializer(serializers.Serializer):
    email = serializers.CharField()
    code = serializers.RegexField(regex=r"^\d{4}$", max_length=4, min_length=4)

    def validate(self, attrs):
        tenant = resolve_tenant_from_request(self.context.get("request"))
        user = find_user_by_email(attrs["email"], tenant=tenant) or find_user_by_email(attrs["email"], tenant=None)

        if (
            not user
            or not user.password_reset_code
            or not secrets.compare_digest(user.password_reset_code, attrs["code"])
            or user.password_reset_code_expired
        ):
            raise serializers.ValidationError({
                "detail": "Kod geçersiz veya süresi dolmuş."
            })

        attrs["user"] = user
        return attrs

class SetNewPasswordSerializer(serializers.Serializer):
    email = serializers.CharField()
    code = serializers.RegexField(regex=r"^\d{4}$", max_length=4, min_length=4)
    new_password = serializers.CharField(min_length=8)

    def validate(self, attrs):
        tenant = resolve_tenant_from_request(self.context.get("request"))
        user = find_user_by_email(attrs["email"], tenant=tenant) or find_user_by_email(attrs["email"], tenant=None)

        if not user:
            raise serializers.ValidationError({"detail": "Kod doğrulama başarısız."})

        try:
            validate_password(attrs["new_password"], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)})

        attrs["user"] = user
        return attrs

    def save(self):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.password_reset_code = None
        user.password_reset_code_sent_at = None
        user.save(update_fields=["password", "password_reset_code", "password_reset_code_sent_at"])
        return user


class UserDeviceSerializer(serializers.ModelSerializer):
    user_info = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()
    user_email = serializers.CharField(source='user.email', read_only=True, default=None)
    user_phone = serializers.CharField(source='user.phone_number', read_only=True, default=None)

    class Meta:
        model = UserDevice
        fields = '__all__'

    def get_user_info(self, obj):
        if not obj.user:
            return None
        user = obj.user
        full_name = user.get_full_name() if hasattr(user, 'get_full_name') else ''
        return {
            'id': str(user.id) if user.id else None,
            'first_name': user.first_name or '',
            'last_name': user.last_name or '',
            'full_name': full_name or user.email or 'Bilinmeyen kullanıcı',
            'email': user.email or '',
            'phone_number': user.phone_number or '',
            'user_type': user.user_type or '',
            'is_active': user.is_active,
            'avatar': getattr(user, 'avatar', None) and (
                user.avatar.url if hasattr(user.avatar, 'url') else str(user.avatar)
            ) or None,
        }

    def get_user_name(self, obj):
        if not obj.user:
            return 'Bilinmeyen kullanıcı'
        return obj.user.get_full_name() or obj.user.email or 'Bilinmeyen kullanıcı'


# =========================
# CheckAuth
# =========================




class CheckAuthSerializer(serializers.ModelSerializer):
    devices = UserDeviceSerializer(many=True, read_only=True)

    unread_notifications_count = serializers.SerializerMethodField()

    user_type_display = serializers.CharField(
        source="get_user_type_display",
        read_only=True
    )

    full_name = serializers.CharField(
        source="get_full_name",
        read_only=True
    )

    approval_status_display = serializers.CharField(
        source="get_approval_status_display",
        read_only=True
    )

    technician_profile_id = serializers.SerializerMethodField()

    is_admin = serializers.SerializerMethodField()
    is_technician = serializers.SerializerMethodField()
    is_manager = serializers.SerializerMethodField()
    mobile_permissions = serializers.SerializerMethodField()
    subscription = serializers.SerializerMethodField()

    tenant_code = serializers.CharField(
        source="tenant.code",
        read_only=True
    )

    PERMISSION_FIELDS = (
        "can_manage_customers",
        "can_manage_inventory",
        "can_manage_accounting",
        "can_manage_notifications",
        "can_manage_hr",
        "can_manage_reports",
        "can_manage_settings",
        "can_manage_services",
        "can_use_global_search",
        "can_manage_users",
        "can_manage_technicians",
    )

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "phone_number",
            "first_name",
            "last_name",
            "full_name",
            "avatar",
            "is_staff",
            "is_platform_admin",
            "is_active",
            "approval_status",
            "approval_status_display",
            "user_type",
            "user_type_display",
            "date_joined",
            "devices",
            "unread_notifications_count",
            "is_admin",
            "is_technician",
            "is_manager",
            "mobile_permissions",
            "tenant_code",
            "technician_profile_id",
            "subscription",
        )

    # -------------------------
    # Simple flags
    # -------------------------

    def get_is_admin(self, obj):
        return obj.user_type == "admin" or obj.is_staff or obj.is_superuser

    def get_is_manager(self, obj):
        return self.get_is_admin(obj)

    def get_is_technician(self, obj):
        return obj.user_type == "technician" and hasattr(obj, "technician_profile")

    def get_technician_profile_id(self, obj):
        tech = getattr(obj, "technician_profile", None)
        return str(tech.id) if tech else None

    def get_unread_notifications_count(self, obj):
        return Notification.objects.filter(user=obj, is_read=False).count()

    # -------------------------
    # Permissions
    # -------------------------

    def get_subscription(self, obj):
        tenant = getattr(obj, 'tenant', None)
        if not tenant:
            return {'status': 'expired', 'is_active': False, 'plan': None, 'ends_at': None, 'days_remaining': 0}
        subscription = tenant.subscription_info()
        if subscription.get('ends_at'):
            subscription['ends_at'] = subscription['ends_at'].isoformat()
        return subscription

    def get_mobile_permissions(self, obj):
        perms = getattr(
            getattr(obj, "technician_profile", None),
            "permissions",
            None
        )

        if self.get_is_admin(obj):
            return {f: True for f in self.PERMISSION_FIELDS}

        if not perms:
            return {}

        return {
            f: bool(getattr(perms, f, False))
            for f in self.PERMISSION_FIELDS
        }