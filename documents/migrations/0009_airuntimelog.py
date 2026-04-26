from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0008_systemsettings_dual_llama_endpoints"),
    ]

    operations = [
        migrations.CreateModel(
            name="AIRuntimeLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "role",
                    models.CharField(
                        db_index=True,
                        help_text="text | vision | ocr",
                        max_length=16,
                    ),
                ),
                (
                    "level",
                    models.CharField(
                        choices=[("info", "Info"), ("warning", "Warning"), ("error", "Error")],
                        default="info",
                        max_length=16,
                    ),
                ),
                ("event", models.CharField(db_index=True, max_length=64)),
                ("model", models.CharField(blank=True, max_length=255)),
                ("base_url", models.CharField(blank=True, max_length=512)),
                ("latency_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("message", models.TextField(blank=True)),
                ("details", models.JSONField(blank=True, null=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
