# Yeni (new) servis durumunun rengini griden (#64748B) yeşile (#16A34A) günceller.

from django.db import migrations


def update_new_status_color(apps, schema_editor):
    ServiceStatus = apps.get_model('services', 'ServiceStatus')
    ServiceStatus.objects.filter(code='new', color='#64748B').update(color='#16A34A')


def reverse_update_new_status_color(apps, schema_editor):
    ServiceStatus = apps.get_model('services', 'ServiceStatus')
    ServiceStatus.objects.filter(code='new', color='#16A34A').update(color='#64748B')


class Migration(migrations.Migration):

    dependencies = [
        ('services', '0002_alter_service_options_service_created_at_and_more'),
    ]

    operations = [
        migrations.RunPython(update_new_status_color, reverse_update_new_status_color),
    ]
