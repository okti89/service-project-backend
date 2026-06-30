from typing import Optional

from tenants.models import Tenant


def resolve_tenant_from_request(request) -> Optional[Tenant]:
    if request is None:
        return None
    payload = getattr(request, "data", {}) or {}
    code = (request.headers.get("X-Tenant-Code") or payload.get("tenant_code") or "").strip().lower()
    if not code:
        return None
    return Tenant.objects.filter(code=code, is_active=True).first()


def tenant_feature(tenant: Optional[Tenant], key: str, default=None):
    if not tenant:
        return default
    data = getattr(tenant, "features", None) or {}
    return data.get(key, default)


def tenant_feature_int(tenant: Optional[Tenant], key: str, default: int) -> int:
    value = tenant_feature(tenant, key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def tenant_feature_bool(tenant: Optional[Tenant], key: str, default: bool = False) -> bool:
    value = tenant_feature(tenant, key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(default)
