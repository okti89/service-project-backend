import json

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from tenants.models import Tenant


class LoginDiagnosticsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(name='Diagnostics company', code='diagnostics')
        self.user = User.objects.create_user(email='appstore-demo@example.com', password='test-secret-123', user_type='admin', is_staff=True, approval_status='approved', tenant=self.tenant)

    def attempt(self, data, endpoint='/api/accounts/auth/login/'):
        with self.assertLogs('login_diagnostics', level='INFO') as logs:
            response = self.client.post(endpoint + '?secret_query=never-log-this', data, format='json', HTTP_AUTHORIZATION='Token secret-token-never-log', HTTP_X_REQUEST_ID='untrusted-request-id', HTTP_USER_AGENT='private-agent-never-log')
        events = [json.loads(record.getMessage()) for record in logs.records]
        serialized = json.dumps(events)
        for secret in ['test-secret-123', 'wrong-secret', 'secret-token-never-log', 'secret_query', 'never-log-this', 'untrusted-request-id', 'private-agent-never-log', self.user.email]:
            self.assertNotIn(secret, serialized)
        self.assertEqual([e['event'] for e in events], ['login_received', 'login_completed'])
        self.assertEqual(events[0]['request_id'], events[1]['request_id'])
        self.assertEqual(response['X-Login-Request-ID'], events[1]['request_id'])
        self.assertEqual(len(response['X-Login-Request-ID']), 32)
        return response, events[1]

    def test_success_and_wrong_credentials_have_safe_distinct_events(self):
        for endpoint in ['/api/accounts/auth/login/', '/api/accounts/admin/login/']:
            response, event = self.attempt({'email': self.user.email, 'password': 'test-secret-123'}, endpoint)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(event['outcome'], 'success')
            self.assertEqual(event['account_kind'], 'review_admin')
            response, event = self.attempt({'email': self.user.email, 'password': 'wrong-secret'}, endpoint)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(event['outcome'], 'invalid_credentials')

    def test_inactive_and_unknown_company_are_distinguished(self):
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        _, event = self.attempt({'email': self.user.email, 'password': 'test-secret-123'})
        self.assertEqual(event['outcome'], 'inactive_account')
        _, event = self.attempt({'email': self.user.email, 'password': 'test-secret-123', 'tenant_code': 'missing-company'})
        self.assertEqual(event['outcome'], 'unknown_company')

    def test_missing_fields_are_logged_without_payload(self):
        response, event = self.attempt({'password': 'wrong-secret'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(event['outcome'], 'invalid_request')

    def test_unrelated_requests_are_not_logged(self):
        with self.assertNoLogs('login_diagnostics', level='INFO'):
            self.client.get('/api/accounts/auth/me/')
