from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from tenants.models import Tenant


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks")
class LoginTenantLockTests(TransactionTestCase):
    def test_login_updates_last_login_while_the_tenant_row_is_locked(self):
        tenant = Tenant.objects.create(name="Locked company", code="locked-company")
        user = get_user_model().objects.create_user(
            email="lock-test@example.invalid",
            password="test-only-password",
            tenant=tenant,
            user_type="admin",
            approval_status="approved",
        )
        lock_connection = connection.copy()
        try:
            lock_connection.set_autocommit(False)
            table = connection.ops.quote_name(Tenant._meta.db_table)
            with lock_connection.cursor() as cursor:
                cursor.execute(f"SELECT id FROM {table} WHERE id = %s FOR UPDATE", [tenant.pk])

            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout TO '750ms'")
            try:
                response = APIClient().post(
                    "/api/accounts/auth/login/",
                    {"email": user.email, "password": "test-only-password"},
                    format="json",
                )
                self.assertEqual(response.status_code, 200)
                user.refresh_from_db(fields=["last_login"])
                self.assertIsNotNone(user.last_login)
            finally:
                with connection.cursor() as cursor:
                    cursor.execute("RESET lock_timeout")
        finally:
            lock_connection.close()
