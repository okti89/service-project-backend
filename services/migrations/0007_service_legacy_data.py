from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('services', '0006_alter_servicestatus_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='service',
            name='legacy_data',
            field=models.JSONField(blank=True, default=dict, editable=False),
        ),
        migrations.AddField(
            model_name='serviceoperations',
            name='legacy_data',
            field=models.JSONField(blank=True, default=dict, editable=False),
        ),
    ]
