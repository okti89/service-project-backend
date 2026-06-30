import os
import re
import uuid
from datetime import datetime


def _safe_slug(value):
    """
    Tenant kodu veya ismini güvenli klasör adına çevirir.
    """
    raw = str(value or "").strip().lower()
    raw = re.sub(r"\s+", "-", raw)
    raw = re.sub(r"[^a-z0-9_-]", "", raw)
    return raw or "public"


def _resolve_tenant_key(instance):
    """
    Model üzerinden tenant bilgisini bulmaya çalışır.
    """

    # instance.tenant
    tenant = getattr(instance, "tenant", None)
    if tenant:
        return getattr(tenant, "code", None) or getattr(tenant, "name", None)

    # instance.service.customer.tenant
    service = getattr(instance, "service", None)
    if service:
        customer = getattr(service, "customer", None)
        if customer:
            tenant = getattr(customer, "tenant", None)
            if tenant:
                return getattr(tenant, "code", None) or getattr(
                    tenant, "name", None
                )

    # instance.technician.user.tenant
    technician = getattr(instance, "technician", None)
    if technician:
        user = getattr(technician, "user", None) or technician
        tenant = getattr(user, "tenant", None)
        if tenant:
            return getattr(tenant, "code", None) or getattr(
                tenant, "name", None
            )

    # instance.customer.tenant
    customer = getattr(instance, "customer", None)
    if customer:
        tenant = getattr(customer, "tenant", None)
        if tenant:
            return getattr(tenant, "code", None) or getattr(
                tenant, "name", None
            )

    # instance.user.tenant
    user = getattr(instance, "user", None)
    if user:
        tenant = getattr(user, "tenant", None)
        if tenant:
            return getattr(tenant, "code", None) or getattr(
                tenant, "name", None
            )

    # Tenant modelinin kendisi
    if instance.__class__.__name__.lower() == "tenant":
        return getattr(instance, "code", None) or getattr(
            instance, "name", None
        )

    return "public"


def tenant_directory_path(instance, filename):
    """
    Örnek çıktı:

    izmir-store/product/2026/06/4f6b8f4c2d5c4e89a4f2.jpg
    """

    tenant_key = _safe_slug(_resolve_tenant_key(instance))

    model_folder = instance._meta.model_name

    ext = os.path.splitext(filename)[1].lower()

    unique_filename = f"{uuid.uuid4().hex}{ext}"

    today = datetime.now()

    return os.path.join(
        tenant_key,
        model_folder,
        str(today.year),
        f"{today.month:02d}",
        unique_filename,
    )