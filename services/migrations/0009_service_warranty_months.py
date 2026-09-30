from django.db import migrations, models


def copy_certificate_months(apps, schema_editor):
    Service = apps.get_model('services', 'Service')
    WarrantyCertificate = apps.get_model('services', 'WarrantyCertificate')
    db_alias = schema_editor.connection.alias
    for service_id, months in WarrantyCertificate.objects.using(db_alias).values_list('service_id', 'warranty_months').iterator():
        Service.objects.using(db_alias).filter(pk=service_id, warranty_months__isnull=True).update(warranty_months=months)


class Migration(migrations.Migration):
    dependencies = [
        ('services', '0008_service_description'),
    ]

    operations = [
        migrations.AddField(
            model_name='service',
            name='warranty_months',
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='Garanti Süresi (Ay)'),
        ),
        migrations.AlterField(
            model_name='warrantycertificate',
            name='warranty_months',
            field=models.PositiveIntegerField(default=12, verbose_name='Garanti Süresi (Ay)'),
        ),
        migrations.RunPython(copy_certificate_months, migrations.RunPython.noop),
    ]
