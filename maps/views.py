"""Harita API endpoint'leri (geocoding + directions + places + distance matrix + static).

Quota uygulama mantigi:
  1) Tenant authenticate olmalidir
  2) Tenant + API tipi bazli aylik kota kontrol edilir
     (services.check_and_increment)
  3) Adres normalize edilip tenant-scoped cache'e bakılır
  4) Asıl API (Photon ucretsiz, opsiyonel Google Maps) cagirilir
  5) Sonuc 7 gunluğune cache'lenir

Quota asildiginda 429 doner. Mobil uygulama bu durumda Photon/OSRM
fallback'ine dusebilir (DB yazmaz, yani kota harcamaz).
"""

import hashlib
import logging

import requests
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from maps.models import MapCache, TenantMapQuota
from maps.services import check_and_increment, current_usage, get_api_limit

logger = logging.getLogger(__name__)


# Asagidaki URL'ler Google Maps API aktif olunca Google'a, olmayinca ucretsiz
# alternatiflere gider. Tenant bazli kota her durumda uygulanir.
PHOTON_URL = "https://photon.komoot.io/api/"
PHOTON_AUTOCOMPLETE_URL = "https://photon.komoot.io/api/"  # ayni endpoint
PHOTON_REVERSE_URL = "https://photon.komoot.io/reverse"
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
GOOGLE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
GOOGLE_PLACES_AUTOCOMPLETE_URL = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
GOOGLE_DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
GOOGLE_STATIC_MAP_URL = "https://maps.googleapis.com/maps/api/staticmap"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"


def _google_key():
    return getattr(settings, "GOOGLE_MAPS_KEY", None) or getattr(
        settings, "MAPS_GOOGLE_KEY", None
    )


def _make_cache_key(parts: list[str]) -> str:
    joined = "|".join(p.strip().lower() for p in parts if p)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _throttled_response(tenant, api_type: str):
    """429 response helper. Tum tipler icin ayni formatta."""
    return Response(
        {
            "error": "QUOTA_EXCEEDED",
            "api_type": api_type,
            "detail": (
                f"Aylık {api_type} istek limiti doldu. "
                "Harici haritaya yönlendiriliyor."
            ),
            **current_usage(tenant, api_type=api_type),
        },
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------

def _photon_geocode(query: str) -> dict | None:
    try:
        resp = requests.get(
            PHOTON_URL,
            params={"q": query, "limit": 1},
            headers={"Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8"},
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.warning("Photon network error: %s", exc)
        return None
    if resp.status_code != 200:
        return None
    data = resp.json()
    features = (data or {}).get("features") or []
    if not features:
        return None
    feature = features[0]
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    if len(coords) < 2:
        return None
    props = feature.get("properties") or {}
    display_name = ", ".join(
        filter(
            None,
            [
                props.get("name"),
                props.get("street"),
                props.get("housenumber"),
                props.get("city") or props.get("town") or props.get("village"),
                props.get("state"),
                props.get("country"),
            ],
        )
    ) or query
    return {
        "latitude": float(coords[1]),
        "longitude": float(coords[0]),
        "display_name": display_name,
        "provider": "photon",
    }


def _google_geocode(query: str, key: str) -> dict | None:
    try:
        resp = requests.get(
            GOOGLE_GEOCODE_URL,
            params={"address": query, "key": key, "language": "tr"},
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.warning("Google geocode network error: %s", exc)
        return None
    if resp.status_code != 200:
        return None
    data = resp.json()
    results = data.get("results") or []
    if not results or data.get("status") not in ("OK", "ZERO_RESULTS"):
        return None
    first = results[0]
    location = (first.get("geometry") or {}).get("location") or {}
    lat = location.get("lat")
    lon = location.get("lng")
    if lat is None or lon is None:
        return None
    return {
        "latitude": float(lat),
        "longitude": float(lon),
        "display_name": first.get("formatted_address") or query,
        "provider": "google",
    }


# Reverse yon (koordinat -> adres) provider'lari. Yon tespiti maps_geocode
# icinde yapilir, bu fonksiyonlar sadece dis servislere istek atar.
def _photon_reverse_geocode(latitude: float, longitude: float) -> dict | None:
    try:
        resp = requests.get(
            PHOTON_REVERSE_URL,
            params={"lon": longitude, "lat": latitude, "limit": 1},
            headers={"Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8"},
            timeout=8,
        )
    except requests.RequestException as exc:
        logger.warning("Photon reverse network error: %s", exc)
        return None
    if resp.status_code != 200:
        return None
    data = resp.json()
    features = (data or {}).get("features") or []
    if not features:
        return None
    feature = features[0]
    props = feature.get("properties") or {}
    display_name = ", ".join(
        filter(
            None,
            [
                props.get("name"),
                props.get("street"),
                props.get("housenumber"),
                props.get("city") or props.get("town") or props.get("village"),
                props.get("state"),
                props.get("country"),
            ],
        )
    )
    if not display_name:
        display_name = f"{latitude}, {longitude}"
    return {
        "latitude": float(latitude),
        "longitude": float(longitude),
        "display_name": display_name,
        "provider": "photon",
    }


def _google_reverse_geocode(latitude: float, longitude: float, key: str) -> dict | None:
    try:
        resp = requests.get(
            GOOGLE_GEOCODE_URL,
            params={"latlng": f"{latitude},{longitude}", "key": key, "language": "tr"},
            timeout=8,
        )
    except requests.RequestException as exc:
        logger.warning("Google reverse network error: %s", exc)
        return None
    if resp.status_code != 200:
        return None
    data = resp.json()
    results = data.get("results") or []
    if not results or data.get("status") not in ("OK", "ZERO_RESULTS"):
        return None
    first = results[0]
    return {
        "latitude": float(latitude),
        "longitude": float(longitude),
        "display_name": first.get("formatted_address") or f"{latitude}, {longitude}",
        "provider": "google",
    }


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def maps_geocode(request):
    """Tek endpoint - iki yön:

    Forward  (adres -> koordinat):
      POST { address: "..." }
    Reverse  (koordinat -> adres):
      GET  ?lat=41.0082&lon=28.9784
      POST { latitude: 41.0082, longitude: 28.9784 }

    Her iki yon ayni 'geocode' api type kotasini kullanir,
    ayni Google → Photon fallback zincirini paylasir,
    ayni 7 gunluk tenant-scoped cache'e yazilir.

    Basarili olursa: { display_name, latitude, longitude, provider, quota, cached, direction }
    """
    tenant = getattr(request.user, "tenant", None)
    if tenant is None:
        return Response({"error": "TENANT_MISSING"}, status=status.HTTP_403_FORBIDDEN)

    # Yon tespiti: once reverse (lat/lon), sonra forward (address)
    direction = None
    address = None
    latitude = None
    longitude = None

    if request.method == "GET":
        lat_param = (request.GET.get("lat") or "").strip()
        lon_param = (request.GET.get("lon") or request.GET.get("lng") or "").strip()
        addr_param = (request.GET.get("address") or "").strip()
    else:
        lat_param = str(request.data.get("lat") or request.data.get("latitude") or "").strip()
        lon_param = str(request.data.get("lon") or request.data.get("lng") or request.data.get("longitude") or "").strip()
        addr_param = (request.data.get("address") or "").strip()

    if lat_param and lon_param:
        try:
            latitude = float(lat_param)
            longitude = float(lon_param)
            direction = "reverse"
        except (TypeError, ValueError):
            return Response({"error": "EMPTY"}, status=400)
    elif addr_param:
        address = addr_param
        direction = "forward"
    else:
        return Response({"error": "EMPTY"}, status=400)

    # Cache key: yon + input
    if direction == "forward":
        cache_input = address
    else:
        # Coord hassasiyeti 5 hane (~1m) - yakin noktalar ayni sonucu verir
        cache_input = f"rev:{latitude:.5f},{longitude:.5f}"

    # Cache-first: oncelikle cache kontrol et, cache hit'te kota ARTIRMA
    cache_key = _make_cache_key([str(tenant.pk), TenantMapQuota.API_GEOCODE, cache_input])
    cached = MapCache.objects.filter(tenant=tenant, cache_key=cache_key).first()
    if cached and not cached.is_expired():
        try:
            usage = current_usage(tenant, api_type=TenantMapQuota.API_GEOCODE)
        except Exception:
            usage = {"used": 0, "limit": 0, "remaining": 0}
        return Response(
            {**cached.result, "quota": usage, "cached": True,
             "from_cache_no_charge": True, "direction": direction}
        )

    # Cache miss: kota kontrolu + artisi
    try:
        quota = check_and_increment(tenant, TenantMapQuota.API_GEOCODE, cost=1)
    except Exception:
        return _throttled_response(tenant, TenantMapQuota.API_GEOCODE)

    # Provider: Google (key varsa) → Photon fallback
    google_key = _google_key()
    if direction == "forward":
        result = _google_geocode(address, google_key) if google_key else None
        if not result:
            result = _photon_geocode(address)
    else:
        result = _google_reverse_geocode(latitude, longitude, google_key) if google_key else None
        if not result:
            result = _photon_reverse_geocode(latitude, longitude)

    if not result:
        return Response(
            {"error": "NOT_FOUND", "quota": quota, "direction": direction},
            status=status.HTTP_404_NOT_FOUND,
        )

    MapCache.objects.update_or_create(
        tenant=tenant,
        cache_key=cache_key,
        defaults={"result": result, "ttl_days": 7},
    )
    return Response({**result, "quota": quota, "cached": False, "direction": direction})


# ---------------------------------------------------------------------------
# Directions
# ---------------------------------------------------------------------------

def _google_directions(origin: str, destination: str, key: str, waypoints: list[str] | None = None) -> dict | None:
    params = {
        "origin": origin,
        "destination": destination,
        "key": key,
        "mode": "driving",
        "language": "tr",
    }
    if waypoints:
        # Google "via:" prefix'i olmadan gonderirsek default olarak en iyi sirayla optimize eder
        params["waypoints"] = "|".join(waypoints)
    try:
        resp = requests.get(
            GOOGLE_DIRECTIONS_URL,
            params=params,
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.warning("Google directions network error: %s", exc)
        return None
    if resp.status_code != 200:
        return None
    data = resp.json()
    if data.get("status") != "OK" or not data.get("routes"):
        return None
    return data


def _parse_latlon_to_osrm(coord_str: str) -> str:
    """'lat,lon' formatini OSRM'nin beklediği 'lon,lat' formatina cevir."""
    parts = coord_str.strip().split(",")
    if len(parts) == 2:
        lat, lon = parts[0].strip(), parts[1].strip()
        return f"{lon},{lat}"
    return coord_str


def _osrm_directions(origin: str, destination: str, waypoints: list[str] | None = None) -> dict | None:
    # OSRM lon,lat sirasiyla koordinat bekler (GeoJSON standardi)
    # Biz lat,lon formatinda aliyoruz, cevirmek gerekiyor
    osrm_origin = _parse_latlon_to_osrm(origin)
    osrm_dest = _parse_latlon_to_osrm(destination)

    if waypoints:
        osrm_waypoints = [_parse_latlon_to_osrm(wp) for wp in waypoints]
        coords = ";".join([osrm_origin, *osrm_waypoints, osrm_dest])
    else:
        coords = f"{osrm_origin};{osrm_dest}"

    try:
        resp = requests.get(
            f"{OSRM_URL}/{coords}",
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.warning("OSRM network error: %s", exc)
        return None
    if resp.status_code != 200:
        return None
    data = resp.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        return None
    return data


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def maps_directions(request):
    """GET ?origin=lat,lon&dest=lat,lon"""
    tenant = getattr(request.user, "tenant", None)
    if tenant is None:
        return Response({"error": "TENANT_MISSING"}, status=status.HTTP_403_FORBIDDEN)

    origin = (request.GET.get("origin") or "").strip()
    destination = (request.GET.get("dest") or "").strip()
    if not origin or not destination:
        return Response({"error": "EMPTY"}, status=400)

    # Opsiyonel waypoints: "lat,lon|lat,lon|..." (arac noktalari, 23 max)
    raw_waypoints = (request.GET.get("waypoints") or "").strip()
    waypoints_list = []
    if raw_waypoints:
        for wp in raw_waypoints.split("|"):
            wp = wp.strip()
            if wp:
                waypoints_list.append(wp)

    # Once cache kontrol et: Eger cache varsa quota artirma!
    cache_key = _make_cache_key(
        [str(tenant.pk), TenantMapQuota.API_DIRECTIONS, origin, destination, raw_waypoints]
    )
    cached = MapCache.objects.filter(tenant=tenant, cache_key=cache_key).first()
    if cached and not cached.is_expired():
        # Cache hit: quota'yi sadece goruntule, artirma
        try:
            usage = current_usage(tenant, api_type=TenantMapQuota.API_DIRECTIONS)
        except Exception:
            usage = {"used": 0, "limit": 0, "remaining": 0}
        return Response({**cached.result, "quota": usage, "cached": True, "from_cache_no_charge": True})

    # Cache miss: quota kontrolu + artisi yap
    try:
        quota = check_and_increment(tenant, TenantMapQuota.API_DIRECTIONS, cost=1)
    except Exception:
        return _throttled_response(tenant, TenantMapQuota.API_DIRECTIONS)

    result = None
    google_key = _google_key()
    if google_key:
        result = _google_directions(origin, destination, google_key, waypoints=waypoints_list)
    if not result:
        result = _osrm_directions(origin, destination, waypoints=waypoints_list)

    if not result:
        return Response(
            {"error": "NOT_FOUND", "quota": quota},
            status=status.HTTP_404_NOT_FOUND,
        )

    MapCache.objects.update_or_create(
        tenant=tenant,
        cache_key=cache_key,
        defaults={"result": result, "ttl_days": 7},
    )
    return Response({**result, "quota": quota, "cached": False})


# ---------------------------------------------------------------------------
# Places Autocomplete
# ---------------------------------------------------------------------------

def _photon_autocomplete(query: str) -> list[dict]:
    """Photon'un 'q' parametresi zaten partial match/autocomplete yapar."""
    try:
        resp = requests.get(
            PHOTON_AUTOCOMPLETE_URL,
            params={"q": query, "limit": 8},
            headers={"Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8"},
            timeout=8,
        )
    except requests.RequestException as exc:
        logger.warning("Photon autocomplete network error: %s", exc)
        return []
    if resp.status_code != 200:
        return []
    features = (resp.json() or {}).get("features") or []
    out = []
    for f in features:
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        props = f.get("properties") or {}
        out.append({
            "latitude": float(coords[1]),
            "longitude": float(coords[0]),
            "display_name": ", ".join(
                filter(
                    None,
                    [
                        props.get("name"),
                        props.get("street"),
                        props.get("city") or props.get("town") or props.get("village"),
                        props.get("state"),
                        props.get("country"),
                    ],
                )
            ),
            "provider": "photon",
        })
    return out


def _google_places_autocomplete(query: str, key: str, session_token: str | None = None) -> list[dict]:
    try:
        params = {"input": query, "key": key, "language": "tr",
                  "components": "country:tr"}
        if session_token:
            params["sessiontoken"] = session_token
        resp = requests.get(GOOGLE_PLACES_AUTOCOMPLETE_URL, params=params, timeout=8)
    except requests.RequestException as exc:
        logger.warning("Google places network error: %s", exc)
        return []
    if resp.status_code != 200:
        return []
    data = resp.json()
    if data.get("status") not in ("OK", "ZERO_RESULTS"):
        return []
    predictions = data.get("predictions") or []
    return [{"description": p.get("description"), "place_id": p.get("place_id"),
             "provider": "google"} for p in predictions]


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def maps_places_autocomplete(request):
    """GET ?q=istanbul&session_token=xxx -> [{ description, place_id?, ... }]"""
    tenant = getattr(request.user, "tenant", None)
    if tenant is None:
        return Response({"error": "TENANT_MISSING"}, status=status.HTTP_403_FORBIDDEN)

    query = (request.GET.get("q") or "").strip()
    if len(query) < 2:
        return Response({"error": "EMPTY", "detail": "En az 2 karakter girin."}, status=400)

    try:
        quota = check_and_increment(tenant, TenantMapQuota.API_PLACES, cost=1)
    except Exception:
        return _throttled_response(tenant, TenantMapQuota.API_PLACES)

    cache_key = _make_cache_key([str(tenant.pk), TenantMapQuota.API_PLACES, query])
    cached = MapCache.objects.filter(tenant=tenant, cache_key=cache_key).first()
    if cached and not cached.is_expired():
        return Response({**cached.result, "quota": quota, "cached": True})

    google_key = _google_key()
    suggestions = None
    if google_key:
        suggestions = _google_places_autocomplete(
            query, google_key, request.GET.get("session_token")
        )
    if suggestions is None or (google_key is None and not suggestions):
        suggestions = _photon_autocomplete(query)

    result = {"suggestions": suggestions}
    MapCache.objects.update_or_create(
        tenant=tenant,
        cache_key=cache_key,
        defaults={"result": result, "ttl_days": 3},
    )
    return Response({**result, "quota": quota, "cached": False})


# ---------------------------------------------------------------------------
# Distance Matrix
# ---------------------------------------------------------------------------

def _google_distance_matrix(origins: str, destinations: str, key: str) -> dict | None:
    try:
        resp = requests.get(
            GOOGLE_DISTANCE_MATRIX_URL,
            params={"origins": origins, "destinations": destinations,
                    "key": key, "language": "tr"},
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.warning("Google distance matrix network error: %s", exc)
        return None
    if resp.status_code != 200:
        return None
    data = resp.json()
    if data.get("status") != "OK":
        return None
    return data


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def maps_distance_matrix(request):
    """GET ?origins=lat,lon|lat,lon&destinations=lat,lon|lat,lon"""
    tenant = getattr(request.user, "tenant", None)
    if tenant is None:
        return Response({"error": "TENANT_MISSING"}, status=status.HTTP_403_FORBIDDEN)

    origins = (request.GET.get("origins") or "").strip()
    destinations = (request.GET.get("destinations") or "").strip()
    if not origins or not destinations:
        return Response({"error": "EMPTY"}, status=400)

    try:
        quota = check_and_increment(tenant, TenantMapQuota.API_DISTANCE_MATRIX, cost=1)
    except Exception:
        return _throttled_response(tenant, TenantMapQuota.API_DISTANCE_MATRIX)

    cache_key = _make_cache_key(
        [str(tenant.pk), TenantMapQuota.API_DISTANCE_MATRIX, origins, destinations]
    )
    cached = MapCache.objects.filter(tenant=tenant, cache_key=cache_key).first()
    if cached and not cached.is_expired():
        return Response({**cached.result, "quota": quota, "cached": True})

    google_key = _google_key()
    result = None
    if google_key:
        result = _google_distance_matrix(origins, destinations, google_key)

    if not result:
        return Response(
            {"error": "GOOGLE_KEY_REQUIRED", "detail": "Distance Matrix icin Google Maps key gerekli."},
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )

    MapCache.objects.update_or_create(
        tenant=tenant,
        cache_key=cache_key,
        defaults={"result": result, "ttl_days": 1},
    )
    return Response({**result, "quota": quota, "cached": False})


# ---------------------------------------------------------------------------
# Static Map (URL proxy)
# ---------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def maps_static_map_url(request):
    """GET ?lat=..&lon=..&zoom=15&w=600&h=400 -> { url, expires_at }"""
    tenant = getattr(request.user, "tenant", None)
    if tenant is None:
        return Response({"error": "TENANT_MISSING"}, status=status.HTTP_403_FORBIDDEN)

    lat = request.GET.get("lat")
    lon = request.GET.get("lon")
    if not lat or not lon:
        return Response({"error": "EMPTY"}, status=400)

    try:
        quota = check_and_increment(tenant, TenantMapQuota.API_STATIC_MAP, cost=1)
    except Exception:
        return _throttled_response(tenant, TenantMapQuota.API_STATIC_MAP)

    google_key = _google_key()
    if not google_key:
        return Response(
            {"error": "GOOGLE_KEY_REQUIRED", "detail": "Static Map icin Google Maps key gerekli."},
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )

    params = {
        "center": f"{lat},{lon}",
        "zoom": request.GET.get("zoom", 15),
        "size": f"{request.GET.get('w', 600)}x{request.GET.get('h', 400)}",
        "key": google_key,
        "markers": f"color:red|{lat},{lon}",
    }
    return Response(
        {
            "url": GOOGLE_STATIC_MAP_URL,
            "params": params,
            "quota": quota,
        }
    )


# ---------------------------------------------------------------------------
# Kullanım özeti
# ---------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def maps_quota(request):
    """Tenant'in TUM harita API'lerinin anlik kullanimini doner. Kota dusmez."""
    tenant = getattr(request.user, "tenant", None)
    if tenant is None:
        return Response({"error": "TENANT_MISSING"}, status=status.HTTP_403_FORBIDDEN)
    return Response(current_usage(tenant))
