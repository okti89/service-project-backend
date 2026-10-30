# RevenueCat company subscriptions

Products (same subscription group/level, max 10 active users including administrator):
- com.servis.asistani.company10.monthly — TRY 1500/month
- com.servis.asistani.company10.yearly — TRY 15000/year

Standard account setup is included. No lifetime, five-year, or mandatory external setup payment.

## Deployment prerequisites

Run migrations before starting the updated server. Set these server-only values:

```
REVENUECAT_SECRET_API_KEY=<V2 read-only server key>
REVENUECAT_APPLE_PUBLIC_SDK_KEY=<appl_ public SDK key>
REVENUECAT_PROJECT_ID=<RevenueCat project id>
REVENUECAT_APPLE_APP_ID=<RevenueCat App Store app id>
REVENUECAT_ENTITLEMENT_ID=company_10
REVENUECAT_WEBHOOK_AUTHORIZATION=<shared Authorization header value>
REVENUECAT_SANDBOX_TENANTS=2026
```

Never add the secret key to Git, mobile assets, public Expo environment variables, logs, or review notes. The V2 key needs only read permissions for customer subscriptions, project apps, and project products. RevenueCat must use **Keep with original App User ID** restore behavior. Sandbox remains limited to named test companies.

Configure RevenueCat webhooks for `/api/billing/revenuecat/webhook/`, both Production and Sandbox, limited to the App Store application and using the configured Authorization header. Configure both Apple App Store Server Notifications V2 environments to RevenueCat's incoming notification URL, then send an Apple test notification after deployment. Schedule `python manage.py reconcile_revenuecat_subscriptions` hourly using the deployment platform; alert on nonzero exit. No recurring job is provisioned automatically.

Account binding requires a signed-in company administrator. Do not configure App Store promotions, contingent pricing, win-back offers, or external redemption codes in the initial release. Apple rejected disabling Streamlined Purchasing until the latest approved binary includes the required StoreKit APIs; revisit the switch after an eligible binary is approved and PurchaseIntent handling is verified. Both plans provide the same service, so place them at the same subscription level.

The profile endpoint reports `store_ready=false` while RevenueCat values are absent, and the client prevents purchase. This flag checks local configuration, not a real transaction: successful Sandbox purchase, server synchronization, restore and webhook delivery are required before release.

Subscriptions bind to a server-generated random company UUID. Client receipt flags cannot grant access. RevenueCat data is retrieved server-side; the App Store app, known product identifiers and `company_10` entitlement are validated before access is granted. Webhooks are authorization-checked and atomically deduplicated. Already-paid manual memberships and demo trials remain valid independently. Expired subscriptions cannot create legacy unlimited access. The user cap is enforced when creating, moving or reactivating users through ordinary ORM saves; bulk SQL/queryset updates must not be used to bypass it. Existing companies with >10 active users require reducing the count before purchasing this plan.

## Validation

```
python manage.py test billing tenants accounts --settings=core.billing_test_settings --noinput
```

Tests use an isolated SQLite database and dummy email/storage configuration, never production data. Row locking is implemented with select_for_update on the tenant and requires PostgreSQL in production; a real PostgreSQL concurrent-activation test remains required. Mocked RevenueCat responses cover authorization, identity, product, entitlement, pagination, expiry, refund, and webhook policy; they do not replace real Apple server/device tests.

## Release gate

Before publishing: configure products/prices/localizations/availability and review screenshots, verify paid agreements/tax/banking, deploy server/migrations/protected configuration, verify notification delivery, test successful/cancelled/pending purchase and restore on a physical iPhone/TestFlight, test monthly↔annual changes and refunds/expiry, verify Android is unaffected, update public privacy text and App Store privacy disclosures, then upload a new native iOS binary and submit the first subscriptions alongside it. Existing build 6 and an OTA alone cannot deliver the RevenueCat native SDK or iOS location-policy changes.
