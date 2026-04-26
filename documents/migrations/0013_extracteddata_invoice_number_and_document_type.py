from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0012_expansion_models_and_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="extracteddata",
            name="document_type",
            field=models.CharField(
                choices=[("receipt", "Receipt"), ("invoice", "Invoice"), ("unknown", "Unknown")],
                db_index=True,
                default="unknown",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="extracteddata",
            name="invoice_number",
            field=models.CharField(blank=True, db_index=True, max_length=128),
        ),
    ]
