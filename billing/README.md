# Apple company subscriptions

Products (same subscription group/level, max 10 active users including administrator):
- com.servis.asistani.company10.monthly — TRY 1500/month
- com.servis.asistani.company10.yearly — TRY 15000/year

Standard account setup is included. No lifetime, five-year, or mandatory external setup payment.

## Deployment prerequisites

Install requirements and run migrations **before** starting the updated server. Existing Docker entrypoint already does this. Set server-only values:

```
APPLE_IAP_KEY_ID=<In-App Purchase key identifier>
APPLE_IAP_ISSUER_ID=<App Store Connect issuer>
APPLE_IAP_PRIVATE_KEY_PATH=<absolute mounted secret path to .p8>
APPLE_IAP_APP_ID=6791547591
APPLE_IAP_SANDBOX_TENANTS=2026
```

Never add the private key to Git, mobile assets, public Expo environment variables, logs, or review notes. Mount it read-only with service-user permissions. Sandbox must remain limited to named test companies; Production is attempted first and fallback occurs only on Apple's Transaction Not Found code.

Configure App Store Server Notifications V2 (Production and Sandbox) to the deployed HTTPS endpoint `/api/billing/apple/notifications/`. Use Apple's test notification and verify successful delivery. Schedule `python manage.py reconcile_apple_subscriptions` hourly using the deployment platform; alert on nonzero exit. No recurring job has been provisioned automatically.

Disable Family Sharing and multiseat purchasing: account binding requires a signed-in company administrator. Do not configure App Store promotions, contingent pricing, win-back offers, or external redemption codes in the initial release. Apple rejected disabling Streamlined Purchasing until the latest approved binary includes the required StoreKit APIs; revisit the switch after an eligible binary is approved and PurchaseIntent handling is verified. Both plans provide the same service, so place them at the same level. Do not enable grace period until grace entitlements are implemented (current verification grants status 1 only).

The profile endpoint reports `store_ready=false` while keys/trust roots are absent, and the client prevents purchase. This flag checks local configuration, not the validity of the Apple credentials: successful server API verification with an actual sandbox transaction is required before release.

Subscriptions bind to a stable random company appAccountToken. Client receipt flags cannot grant access. Current Apple transaction/status is verified server-side before acknowledging a transaction on the phone. Webhooks are deduplicated atomically; stale signed transactions cannot overwrite newer ones. Already-paid manual memberships and demo trials remain valid independently. Expired Apple subscriptions cannot create legacy unlimited access. The user cap is enforced when creating, moving or reactivating users through ordinary ORM saves; bulk SQL/queryset updates must not be used to bypass it. Existing companies with >10 active users require reducing the count before purchasing this plan; no automatic deletion/deactivation is performed.

## Validation

```
python manage.py test billing tenants accounts --settings=core.billing_test_settings --noinput
```

Tests use an isolated SQLite database and dummy email/storage configuration, never production data. Row locking is implemented with select_for_update on the tenant and requires PostgreSQL in production; a real PostgreSQL concurrent-activation test remains required. Cryptographic failure paths and entitlement policy use mocked Apple responses; they do not replace real Apple server/device tests.

The public Apple trust roots were downloaded from https://www.apple.com/certificateauthority/ on 2026-10-28. Public certificates are not signing credentials.

## Release gate

Before publishing: configure products/prices/localizations/availability and current paywall review screenshots, verify paid agreements/tax/banking, deploy server/migrations/secret mount, verify notification delivery, test successful/cancelled/pending purchase and restore on a physical iPhone/TestFlight, test monthly↔annual changes and refunds/expiry, verify Android is unaffected, update public privacy text and App Store privacy disclosures, then upload a new native iOS binary and submit the first subscriptions alongside it. Existing build 6 and an OTA alone cannot deliver StoreKit/native location changes.
