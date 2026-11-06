"""Credential-free diagnostics for public sign-in requests."""
import json
import logging
import time
import uuid
from datetime import datetime, timezone


logger = logging.getLogger('login_diagnostics')
LOGIN_PATHS = {'/api/accounts/auth/login/', '/api/accounts/admin/login/'}
REASONS = {'invalid_credentials', 'unknown_company', 'inactive_account', 'not_admin', 'approval_pending'}


def mark_login_result(request, reason, email):
    if request is None:
        return
    raw_request = getattr(request, '_request', request)
    raw_request.login_failure_reason = reason
    raw_request.login_account_kind = {
        'appstore-demo@example.com': 'review_admin',
        'appstore-user1@example.com': 'review_technician',
    }.get(str(email or '').strip().lower(), 'other')


class LoginDiagnosticsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path not in LOGIN_PATHS or request.method != 'POST':
            return self.get_response(request)
        started = time.monotonic()
        request_id = uuid.uuid4().hex
        common = {'request_id': request_id, 'route': request.path}
        # Never serialize the request, body, query, headers, exceptions or user.
        logger.info(json.dumps({**common, 'event': 'login_received', 'at_utc': datetime.now(timezone.utc).isoformat()}))
        response = self.get_response(request)
        status = response.status_code
        reason = getattr(request, 'login_failure_reason', None)
        if 200 <= status < 300:
            outcome = 'success'
        elif reason in REASONS:
            outcome = reason
        else:
            outcome = {400: 'invalid_request', 401: 'authentication_rejected', 403: 'access_denied', 429: 'rate_limited'}.get(status, 'server_error' if status >= 500 else 'request_rejected')
        account_kind = getattr(request, 'login_account_kind', 'unknown')
        if account_kind not in {'review_admin', 'review_technician', 'other'}:
            account_kind = 'unknown'
        logger.info(json.dumps({**common, 'event': 'login_completed', 'at_utc': datetime.now(timezone.utc).isoformat(), 'status': status, 'outcome': outcome, 'account_kind': account_kind, 'duration_ms': round((time.monotonic() - started) * 1000)}))
        response['X-Login-Request-ID'] = request_id
        return response
