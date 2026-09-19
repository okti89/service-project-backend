from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('tenants', '0003_tenantmembership_plan'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tenantmembership',
            name='renewal_date',
            field=models.DateField(blank=True),
        ),
    ]
