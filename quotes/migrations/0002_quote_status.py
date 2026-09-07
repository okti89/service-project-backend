from django.db import migrations, models


def set_existing_quote_statuses(apps, schema_editor):
    Quote = apps.get_model("quotes", "Quote")
    Quote.objects.filter(sent_at__isnull=False).update(status="sent")
    Quote.objects.filter(converted_service__isnull=False).update(status="converted")


def reset_quote_statuses(apps, schema_editor):
    Quote = apps.get_model("quotes", "Quote")
    Quote.objects.all().update(status="draft")


class Migration(migrations.Migration):
    dependencies = [
        ("quotes", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="quote",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Taslak"),
                    ("sent", "Gönderildi"),
                    ("cancelled", "İptal Edildi"),
                    ("converted", "Servise Dönüştürüldü"),
                ],
                default="draft",
                max_length=20,
            ),
        ),
        migrations.RunPython(set_existing_quote_statuses, reset_quote_statuses),
    ]
