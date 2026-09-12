from collections import defaultdict

from django.contrib.auth.hashers import make_password
from django.core.management.base import CommandError
from django.test import TestCase

from accounts.models import User
from services.management.commands.import_biservisim import Command, normalized_key
from technicians.models import Technician
from tenants.models import Tenant


class BiServisimTechnicianMappingTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Uygar Mekanik', code='1001')

    def command_for(self, legacy_name, mapping):
        command = Command()
        command.tenant = self.tenant
        command.tenant_code = self.tenant.code
        command.tables = {
            'servis_hizmetlerimiz': [
                {'teknisyen_adi_soyadi': legacy_name},
            ],
            'malzeme_arac_kullanilan': [],
        }
        command.stats = defaultdict(int)
        command.technician_map = {
            normalized_key(legacy_name): mapping,
        }
        return command

    def test_existing_user_is_linked_without_changing_account_fields(self):
        user = User.objects.create_user(
            email='existing@example.com',
            password='CurrentPassword123!',
            tenant=self.tenant,
            first_name='Canli',
            last_name='Kullanici',
            user_type='admin',
            approval_status='pending',
            is_active=False,
            is_staff=True,
        )
        original_password = user.password
        command = self.command_for('ESKI TEKNISYEN', {
            'mode': 'existing',
            'user_id': str(user.id),
            'email': user.email,
            'password_hash': '',
        })

        command._import_technicians()

        user.refresh_from_db()
        self.assertEqual(user.first_name, 'Canli')
        self.assertEqual(user.last_name, 'Kullanici')
        self.assertEqual(user.user_type, 'admin')
        self.assertEqual(user.approval_status, 'pending')
        self.assertFalse(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertEqual(user.password, original_password)
        self.assertTrue(Technician.objects.filter(user=user, tenant=self.tenant).exists())

    def test_new_user_gets_mapped_email_and_hashed_initial_password(self):
        password = 'InitialPassword123!'
        command = self.command_for('YENI TEKNISYEN', {
            'mode': 'create',
            'user_id': '',
            'email': 'yeni.teknisyen@uygarmekanik.com',
            'password_hash': make_password(password),
        })

        command._import_technicians()

        user = User.objects.get(email='yeni.teknisyen@uygarmekanik.com')
        self.assertEqual(user.tenant, self.tenant)
        self.assertEqual(user.user_type, 'technician')
        self.assertEqual(user.approval_status, 'approved')
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password(password))
        self.assertTrue(Technician.objects.filter(user=user, tenant=self.tenant).exists())

    def test_existing_user_from_another_tenant_stops_import(self):
        other_tenant = Tenant.objects.create(name='Other', code='other')
        user = User.objects.create_user(
            email='other@example.com',
            password='CurrentPassword123!',
            tenant=other_tenant,
        )
        command = self.command_for('ESKI TEKNISYEN', {
            'mode': 'existing',
            'user_id': str(user.id),
            'email': user.email,
            'password_hash': '',
        })

        with self.assertRaisesMessage(CommandError, 'baska tenant'):
            command._import_technicians()
