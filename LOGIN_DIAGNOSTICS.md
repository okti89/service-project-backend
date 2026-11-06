# Sign-in diagnostics

Public POST sign-in endpoints emit two JSON events to the application console, visible in Coolify application Logs:

- `login_received`: request reached Django, UTC timestamp, server-generated request ID, fixed route.
- `login_completed`: same ID, HTTP status, duration in milliseconds, outcome and account category.

Search for `login_completed`, then `review_admin` or `review_technician` to find the two review accounts. Other accounts are labelled `other`; no email address is written. Requests failing before credential validation have category `unknown`.

Outcomes include `success`, `invalid_credentials` (unknown email or wrong password, deliberately combined), `unknown_company`, `inactive_account`, `not_admin`, `approval_pending`, `invalid_request`, `authentication_rejected`, `access_denied`, `rate_limited`, and `server_error`. Login authorization and validation behavior are unchanged.

The response includes `X-Login-Request-ID`. Client-supplied IDs are not trusted or logged. No password, token, email, IP address, user-agent, request body, query string, arbitrary header, or exception text is included in these diagnostic records.

Use Apple's reported attempt time to correlate events. No matching received event means only that the request was not observed at Django; inspect proxy/network logs separately. It does not prove a particular DNS, TLS, connectivity, or client error. A received event without completion can indicate interrupted handling. A successful server response does not prove the device received or processed it.

These are container console logs, not a database audit trail. Retention, rotation, and survival of deployment/container replacement depend on the hosting log configuration. Preserve relevant lines promptly when investigating a review; do not claim indefinite retention.
