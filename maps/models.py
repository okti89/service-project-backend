"""Harita API'si icin veritabaninda tutulan modeller.

- TenantMapQuota: Tenant bazli AYLIK ve API-TIPI bazli istek sayaci
  (Redis'siz rate limit, Google Maps ucretlendirmesine uygun)
- MapQuotaPolicy: Tenant bazli (veya global) kota limitleri. DB'den yonetilir,
  admin panelden degistirilebilir, tenant tier'larina gore override edilebilir.
- MapCache: Ayni adres/coordinat icin tekrar API cagirmamak adina tenant-scoped cache
"""

from datetime import timedelta

from django.db import models
from django.utils import timezone


class TenantMapQuota(models.Model):
    """Her tenant icin aylik ve API tipi bazli harita kullanim sayaci.

    Google Maps Platform'da her urunun ayri kotasi var (Geocoding,
    Directions, Places, Distance Matrix, Static Map, Maps JS). Bu yuzden
    unique_together (tenant, api_type, year, month) ile her ay her urun
    icin tek bir satir tutulur.

    select_for_update + F() ile atomik artim yapilir (race condition yok).
    """

    API_GEOCODE = "geocode"
    API_DIRECTIONS = "directions"
    API_PLACES = "places"
    API_DISTANCE_MATRIX = "distance_matrix"
    API_STATIC_MAP = "static_map"
    API_JS = "js"

    API_CHOICES = [
        (API_GEOCODE, "Geocoding"),
        (API_DIRECTIONS, "Directions"),
        (API_PLACES, "Places (autocomplete)"),
        (API_DISTANCE_MATRIX, "Distance Matrix"),
        (API_STATIC_MAP, "Static Map"),
        (API_JS, "Maps JavaScript"),
    ]

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="map_quotas",
    )
    api_type = models.CharField(max_length=32, choices=API_CHOICES, db_index=True)
    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField()
    request_count = models.PositiveIntegerField(default=0)
    last_request_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("tenant", "api_type", "year", "month")
        indexes = [
            models.Index(fields=["tenant", "api_type", "year", "month"]),
            models.Index(fields=["tenant", "year", "month"]),
        ]
        verbose_name = "Tenant Harita Kotası"
        verbose_name_plural = "Tenant Harita Kotaları"

    def __str__(self):
        return f"{self.tenant_id} {self.api_type} {self.year}-{self.month:02d}: {self.request_count}"


class MapQuotaPolicy(models.Model):
    """Tenant bazli (veya global) harita kota limitleri.

    Limitler settings/env'de degil, bu tabloda tutulur. Boylece:
      - Admin panelden degistirilebilir (deploy gerektirmez)
      - Tenant tier'larina gore override edilebilir (Free / Pro / Enterprise)
      - Audit trail (updated_by, updated_at) ile kim ne zaman degistirdi bilinir
      - Pasif politika is_active=False ile devre disi birakilabilir

    Oncelik sirasi (yukaridan asagi):
      1) Tenant'a ozel aktif politika (varsa)
      2) Global aktif politika (varsa)
      3) settings.py default (DB'de hicbir politika yoksa)
    """

    SCOPE_GLOBAL = "global"
    SCOPE_TENANT = "tenant"
    SCOPE_CHOICES = [
        (SCOPE_GLOBAL, "Global (tüm tenant'lar)"),
        (SCOPE_TENANT, "Tenant özel"),
    ]

    scope = models.CharField(max_length=16, choices=SCOPE_CHOICES, default=SCOPE_TENANT, db_index=True)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="map_quota_policies",
        null=True,
        blank=True,
        help_text="Global politika icin bos birakin.",
    )
    api_type = models.CharField(max_length=32, choices=TenantMapQuota.API_CHOICES, db_index=True)
    monthly_limit = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_map_policies",
    )

    class Meta:
        # Global politika tenant=NULL ile temsil edilir, o yuzden
        # unique_together (scope, tenant, api_type) ile cakisma onlenir.
        # MySQL/SQLite'ta NULL degerler unique'i etkilemediginden
        # (scope, api_type) kombinasyonunda sadece bir global satir olabilir.
        constraints = [
            models.UniqueConstraint(
                fields=["scope", "tenant", "api_type"],
                name="uniq_quota_policy_scope_tenant_api",
            ),
        ]
        indexes = [
            models.Index(fields=["scope", "api_type", "is_active"]),
            models.Index(fields=["tenant", "api_type", "is_active"]),
        ]
        verbose_name = "Harita Kota Politikası"
        verbose_name_plural = "Harita Kota Politikaları"

    def __str__(self):
        target = f"tenant={self.tenant_id}" if self.tenant else "GLOBAL"
        status = "✓" if self.is_active else "✗"
        return f"{status} {target} {self.api_type}: {self.monthly_limit}/ay"


class MapCache(models.Model):
    """Tenant bazli adres/coordinat cache. Redis'siz persist cache.

    Map cache genelde 7 gun gecerli olur (adresler degismez).
    """

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="map_caches",
    )
    cache_key = models.CharField(max_length=64, db_index=True)
    result = models.JSONField()
    ttl_days = models.PositiveIntegerField(default=7)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("tenant", "cache_key")
        indexes = [models.Index(fields=["tenant", "cache_key"])]
        verbose_name = "Harita Cache"
        verbose_name_plural = "Harita Cache'leri"

    def is_expired(self) -> bool:
        return timezone.now() > self.created_at + timedelta(days=self.ttl_days)

    def __str__(self):
        return f"{self.tenant_id} {self.cache_key[:10]}..."
