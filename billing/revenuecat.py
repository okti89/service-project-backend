"""Read RevenueCat v2 with a read-only key; normalize only verified store data."""
from datetime import datetime, timezone as datetime_timezone
from urllib.parse import quote, urljoin, urlsplit
import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from .catalog import BUNDLE_ID, PRODUCTS

BASE_URL = 'https://api.revenuecat.com/v2/'

class StoreUnavailable(Exception):
    pass

class InvalidStoreData(Exception):
    pass

def is_configured():
    return bool(getattr(settings, 'REVENUECAT_APPLE_PUBLIC_SDK_KEY', '').startswith('appl_') and
                getattr(settings, 'REVENUECAT_SECRET_API_KEY', '').startswith('sk_') and
                getattr(settings, 'REVENUECAT_PROJECT_ID', '').startswith('proj') and
                getattr(settings, 'REVENUECAT_APPLE_APP_ID', '').startswith('app') and
                getattr(settings, 'REVENUECAT_ENTITLEMENT_ID', ''))

def _get(url, missing_customer=False):
    try:
        response = requests.get(url, headers={'Authorization': 'Bearer ' + settings.REVENUECAT_SECRET_API_KEY,
            'Accept': 'application/json'}, timeout=(5, 15), allow_redirects=False)
        if response.status_code == 404 and missing_customer:
            return {'object': 'list', 'items': [], 'next_page': None}
        if response.status_code != 200:
            raise StoreUnavailable('RevenueCat request failed')
        payload = response.json()
        if not isinstance(payload, dict):
            raise InvalidStoreData('Malformed RevenueCat response')
        return payload
    except (requests.RequestException, ValueError) as exc:
        raise StoreUnavailable('RevenueCat could not be reached') from exc

def _items(url, missing_customer=False):
    expected = urlsplit(url)
    result = []
    seen = set()
    for _ in range(10):
        if url in seen:
            raise InvalidStoreData('Repeated pagination cursor')
        seen.add(url)
        page = _get(url, missing_customer=missing_customer)
        if not isinstance(page.get('items'), list):
            raise InvalidStoreData('Malformed RevenueCat list')
        result.extend(page['items'])
        next_page = page.get('next_page')
        if not next_page:
            return result
        if not isinstance(next_page, str):
            raise InvalidStoreData('Malformed pagination URL')
        url = urljoin(BASE_URL, next_page)
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc != 'api.revenuecat.com' or parsed.path != expected.path:
            raise InvalidStoreData('Unexpected pagination destination')
    raise StoreUnavailable('Subscription history exceeds reconciliation limit')

def _verify_app(project_url):
    app_id = settings.REVENUECAT_APPLE_APP_ID
    cache_key = 'rc-app-verified:' + settings.REVENUECAT_PROJECT_ID + ':' + app_id
    if cache.get(cache_key):
        return
    app = _get(project_url + '/apps/' + quote(app_id, safe=''))
    if app.get('id') != app_id or app.get('type') != 'app_store' or app.get('app_store', {}).get('bundle_id') != BUNDLE_ID:
        raise InvalidStoreData('RevenueCat app does not match the Apple bundle')
    cache.set(cache_key, True, 300)

def _product(project_url, product_id):
    cache_key = 'rc-product:' + settings.REVENUECAT_PROJECT_ID + ':' + product_id
    product = cache.get(cache_key)
    if product is None:
        raw = _get(project_url + '/products/' + quote(product_id, safe=''))
        product = {name: raw.get(name) for name in ('id', 'app_id', 'type', 'store_identifier')}
        cache.set(cache_key, product, 300)
    if product.get('id') != product_id or product.get('app_id') != settings.REVENUECAT_APPLE_APP_ID or product.get('type') != 'subscription':
        raise InvalidStoreData('RevenueCat product belongs to another app or product type')
    return product

def _iso_milliseconds(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise InvalidStoreData('Missing subscription expiry')
    try:
        return datetime.fromtimestamp(value / 1000, tz=datetime_timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError) as exc:
        raise InvalidStoreData('Invalid subscription expiry') from exc

def fetch_customer(app_user_id):
    if not is_configured():
        raise StoreUnavailable('RevenueCat is not configured')
    started_at = timezone.now()
    project_url = BASE_URL + 'projects/' + quote(settings.REVENUECAT_PROJECT_ID, safe='')
    _verify_app(project_url)  # Detect invalid keys/project/app before interpreting a missing customer.
    customer_id = str(app_user_id)
    url = project_url + '/customers/' + quote(customer_id, safe='') + '/subscriptions'
    rows = _items(url, missing_customer=True)
    candidates = []
    for row in rows:
        if not isinstance(row, dict):
            raise InvalidStoreData('Malformed subscription row')
        if row.get('customer_id') != customer_id or row.get('original_customer_id') != customer_id:
            raise InvalidStoreData('Subscription is not owned by this company')
        if row.get('store') != 'app_store':
            continue
        product_id = row.get('product_id')
        if not isinstance(product_id, str):
            raise InvalidStoreData('Missing RevenueCat product ID')
        product = _product(project_url, product_id)
        sku = product['store_identifier']
        if sku not in PRODUCTS:
            continue
        environment = row.get('environment')
        if environment not in ('production', 'sandbox'):
            raise InvalidStoreData('Unknown store environment')
        entitlements = row.get('entitlements')
        if not isinstance(entitlements, dict) or not isinstance(entitlements.get('items'), list) or entitlements.get('next_page'):
            subscription_id = row.get('id')
            if not isinstance(subscription_id, str):
                raise InvalidStoreData('Missing subscription ID')
            entitlement_rows = _items(project_url + '/subscriptions/' + quote(subscription_id, safe='') + '/entitlements')
        else:
            entitlement_rows = entitlements['items']
        if not any(isinstance(item, dict) and item.get('lookup_key') == settings.REVENUECAT_ENTITLEMENT_ID and item.get('state') == 'active' for item in entitlement_rows):
            continue
        expiry = _iso_milliseconds(row.get('ends_at'))
        if not isinstance(row.get('gives_access'), bool) or not isinstance(row.get('pending_payment'), bool):
            raise InvalidStoreData('Missing subscription access state')
        access = row['gives_access'] and not row['pending_payment']
        candidates.append((access and row['ends_at'] > started_at.timestamp()*1000, row['ends_at'], sku, expiry, environment, access))
    subscriber = {'original_app_user_id': customer_id, 'entitlements': {}, 'subscriptions': {}}
    if candidates:
        _, _, sku, expiry, environment, access = max(candidates)
        subscriber['entitlements'][settings.REVENUECAT_ENTITLEMENT_ID] = {'product_identifier': sku, 'expires_date': expiry}
        subscriber['subscriptions'][sku] = {'store': 'app_store', 'is_sandbox': environment == 'sandbox',
            'expires_date': expiry, 'gives_access': access}
    return {'request_date_ms': int(started_at.timestamp()*1000), 'subscriber': subscriber}
