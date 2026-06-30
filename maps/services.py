"""Tenant bazli, API tipi bazli aylik harita kotasini atomik sekilde kontrol eden servis.

Limit nereden gelir (oncelik sirasi):
  1) MapQuotaPolicy - tenant'a ozel aktif politika (DB)
  2) MapQuotaPolicy - global aktif politika (DB)
  3) settings.py'den MAPS_QUOTA_X env degiskeni (default)

Redis veya Celery gibi dis bagimliliklara ihtiyac duymaz; sadece DB kilit
mekanizmasina (select_for_update) guvenir.
"""

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import Throttled

from maps.models import TenantMapQuota

# Default aylik limitler. Sadece DB'de hicbir politika yoksa kullanilir.
# .env ile override edilebilir (orn. MAPS_QUOTA_GEOCODE=2000).
DEFAULT_LIMITS = {
    "geocode": 1000,
    "directions": 1000,
    "places": 500,
    "distance_matrix": 1000,
    "static_map": 500,
    "js": 10000,
}


def get_api_types():
    """Desteklenen API tiplerinin listesini doner."""
    return list(DEFAULT_LIMITS.keys())


def get_api_limit(api_type: str, tenant=None) -> int:
    """Belirli bir API tipinin aylik limitini doner.

    Oncelik sirasi:
      1) Tenant'a ozel aktif politika
      2) Global aktif politika
      3) settings.py env degeri
      4) DEFAULT_LIMITS hardcoded
    """
    # 1 & 2) DB'den politikalari oku
    from maps.models import MapQuotaPolicy

    qs = MapQuotaPolicy.objects.filter(api_type=api_type, is_active=True)

    if tenant is not None:
        tenant_policy = qs.filter(scope=MapQuotaPolicy.SCOPE_TENANT, tenant=tenant).first()
        if tenant_policy:
            return int(tenant_policy.monthly_limit)

    global_policy = qs.filter(scope=MapQuotaPolicy.SCOPE_GLOBAL, tenant__isnull=True).first()
    if global_policy:
        return int(global_policy.monthly_limit)

    # 3) settings/env
    from django.conf import settings

    key = f"MAPS_QUOTA_{api_type.upper()}"
    return int(getattr(settings, key, DEFAULT_LIMITS.get(api_type, 1000)))


def get_all_limits(tenant=None) -> dict:
    """Tum API tipleri icin anlik limit haritasi doner (tenant-aware)."""
    return {api: get_api_limit(api, tenant=tenant) for api in get_api_types()}


def _next_reset_iso(year: int, month: int) -> str:
    if month == 12:
        nxt_year, nxt_month = year + 1, 1
    else:
        nxt_year, nxt_month = year, month + 1
    return f"{nxt_year}-{nxt_month:02d}-01T00:00:00Z"


def check_and_increment(tenant, api_type: str, cost: int = 1) -> dict:
    """Tenant'in belirli bir API tipi icin bu ayki kotasini atomik artirir.

    Limit kaynagi DB'deki MapQuotaPolicy (tenant > global) veya settings/env
    fallback'idir. Limit asildiginda Throttled (429) raise eder.
    """
    if tenant is None:
        raise Throttled(detail={"error": "TENANT_MISSING"})

    if api_type not in DEFAULT_LIMITS:
        raise Throttled(detail={"error": "UNKNOWN_API_TYPE", "api_type": api_type})

    if cost < 1:
        cost = 1

    now = timezone.now()
    year, month = now.year, now.month
    limit = get_api_limit(api_type, tenant=tenant)

    with transaction.atomic():
        row, _ = TenantMapQuota.objects.select_for_update().get_or_create(
            tenant=tenant,
            api_type=api_type,
            year=year,
            month=month,
            defaults={"request_count": 0},
        )

        new_total = row.request_count + cost
        if new_total > limit:
            raise Throttled(detail={
                "error": "QUOTA_EXCEEDED",
                "api_type": api_type,
                "used": row.request_count,
                "limit": limit,
                "limit_reached": True,
                "reset_at": _next_reset_iso(year, month),
            })

        TenantMapQuota.objects.filter(pk=row.pk).update(
            request_count=F("request_count") + cost
        )
        return {
            "api_type": api_type,
            "used": new_total,
            "limit": limit,
            "remaining": max(0, limit - new_total),
            "reset_at": _next_reset_iso(year, month),
        }


def current_usage(tenant, api_type: str | None = None) -> dict:
    """Salt okuma. Tek bir API tipi veya tum tiplerin anlik kullanimini doner.

    Limit kaynagi da ayni oncelik zinciri ile cozulur (tenant > global > env).
    """
    if tenant is None:
        if api_type:
            limit = get_api_limit(api_type, tenant=None)
            return {
                "api_type": api_type,
                "used": 0,
                "limit": limit,
                "remaining": limit,
                "reset_at": _next_reset_iso(timezone.now().year, timezone.now().month),
            }
        return {api: {
            "used": 0,
            "limit": get_api_limit(api, tenant=None),
            "remaining": get_api_limit(api, tenant=None),
        } for api in get_api_types()}

    now = timezone.now()
    year, month = now.year, now.month
    reset_at = _next_reset_iso(year, month)

    if api_type:
        if api_type not in DEFAULT_LIMITS:
            raise ValueError(f"Unknown api_type: {api_type}")
        limit = get_api_limit(api_type, tenant=tenant)
        row = TenantMapQuota.objects.filter(
            tenant=tenant, api_type=api_type, year=year, month=month
        ).first()
        used = row.request_count if row else 0
        return {
            "api_type": api_type,
            "used": used,
            "limit": limit,
            "remaining": max(0, limit - used),
            "reset_at": reset_at,
        }

    # Tum tipler
    rows = TenantMapQuota.objects.filter(tenant=tenant, year=year, month=month)
    used_by_type = {r.api_type: r.request_count for r in rows}
    return {
        api: {
            "used": used_by_type.get(api, 0),
            "limit": get_api_limit(api, tenant=tenant),
            "remaining": max(0, get_api_limit(api, tenant=tenant) - used_by_type.get(api, 0)),
            "reset_at": reset_at,
        }
        for api in get_api_types()
    }
