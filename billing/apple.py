"""Apple is the authority. Never grant access from client supplied receipt fields."""
from functools import lru_cache
from pathlib import Path
from django.conf import settings
from appstoreserverlibrary.api_client import AppStoreServerAPIClient, APIException
from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier
from appstoreserverlibrary.models.Environment import Environment
from .catalog import BUNDLE_ID

class StoreUnavailable(Exception):
    pass

class InvalidPurchase(Exception):
    pass

@lru_cache(maxsize=2)
def clients(environment):
    try:
        key_path = getattr(settings, 'APPLE_IAP_PRIVATE_KEY_PATH', '')
        key_id = getattr(settings, 'APPLE_IAP_KEY_ID', '')
        issuer_id = getattr(settings, 'APPLE_IAP_ISSUER_ID', '')
        app_id = getattr(settings, 'APPLE_IAP_APP_ID', 6791547591)
        if not all((key_path, key_id, issuer_id, app_id)):
            raise StoreUnavailable('Apple billing is not configured')
        certs = [p.read_bytes() for p in sorted((Path(__file__).parent / 'certificates').glob('*.cer'))]
        if len(certs) < 3:
            raise StoreUnavailable('Apple trust roots are missing')
        return (
            AppStoreServerAPIClient(Path(key_path).read_bytes(), key_id, issuer_id, BUNDLE_ID, environment),
            SignedDataVerifier(certs, True, environment, BUNDLE_ID, int(app_id)),
        )
    except (OSError, ValueError) as exc:
        raise StoreUnavailable('Apple billing configuration is invalid') from exc

def allow_sandbox(tenant):
    return tenant.code in getattr(settings, 'APPLE_IAP_SANDBOX_TENANTS', [])

def fetch_current(transaction_id, tenant):
    environments = [Environment.PRODUCTION]
    if allow_sandbox(tenant):
        environments.append(Environment.SANDBOX)
    for index, environment in enumerate(environments):
        client, verifier = clients(environment)
        try:
            info = client.get_transaction_info(transaction_id)
            initial = verifier.verify_and_decode_signed_transaction(info.signedTransactionInfo)
            response = client.get_all_subscription_statuses(initial.originalTransactionId)
            for group in response.data or []:
                for last in group.lastTransactions or []:
                    if last.originalTransactionId == initial.originalTransactionId:
                        current = verifier.verify_and_decode_signed_transaction(last.signedTransactionInfo)
                        return current, int(last.status), environment.value
            raise InvalidPurchase('Subscription not found')
        except APIException as exc:
            # A production lookup may return Not Found for a sandbox transaction.
            # Other failures must never downgrade verification to sandbox.
            if getattr(exc, 'raw_api_error', None) == 4040010 and index + 1 < len(environments):
                continue
            raise StoreUnavailable('Apple could not verify the transaction') from exc
        except InvalidPurchase:
            raise
        except Exception as exc:
            raise InvalidPurchase('Apple signature verification failed') from exc
    raise InvalidPurchase('Transaction not found')

def decode_notification(payload):
    # Environment is not trusted until Apple verifies the entire notification.
    for environment in (Environment.PRODUCTION, Environment.SANDBOX):
        _, verifier = clients(environment)
        try:
            result = verifier.verify_and_decode_notification(payload)
            if getattr(result.notificationType, 'value', result.notificationType) == 'TEST':
                return result, None, environment.value
            if not result.data or not result.data.signedTransactionInfo:
                raise InvalidPurchase('Notification has no subscription transaction')
            transaction = verifier.verify_and_decode_signed_transaction(result.data.signedTransactionInfo)
            return result, transaction, environment.value
        except InvalidPurchase:
            raise
        except Exception:
            continue
    raise InvalidPurchase('Notification signature is invalid')
