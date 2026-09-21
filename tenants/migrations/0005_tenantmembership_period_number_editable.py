from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('tenants', '0004_tenantmembership_renewal_date_editable'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tenantmembership',
            name='period_number',
            field=models.PositiveIntegerField(),
        ),
    ]
