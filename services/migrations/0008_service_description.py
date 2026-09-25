from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('services', '0007_service_legacy_data'),
    ]

    operations = [
        migrations.AddField(
            model_name='service',
            name='description',
            field=models.TextField(blank=True, default='', verbose_name='Servis Açıklaması'),
        ),
    ]
