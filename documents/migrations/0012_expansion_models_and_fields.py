from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0011_invoicedocument_extraction_attempts_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="invoicedocument",
            name="canonical_document",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="duplicates",
                to="documents.invoicedocument",
            ),
        ),
        migrations.AddField(
            model_name="invoicedocument",
            name="duplicate_confidence",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="invoicedocument",
            name="duplicate_group",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="invoicedocument",
            name="duplicate_reason",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="invoicedocument",
            name="file_sha256",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="invoicedocument",
            name="first_processing_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="invoicedocument",
            name="is_duplicate",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="invoicedocument",
            name="last_processing_finished_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="invoicedocument",
            name="last_processing_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="invoicedocument",
            name="verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="systemsettings",
            name="enable_duplicate_detection",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="systemsettings",
            name="enable_webhooks",
            field=models.BooleanField(default=True),
        ),
        migrations.CreateModel(
            name="ApiKey",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=128)),
                ("key_prefix", models.CharField(max_length=16, unique=True)),
                ("key_hash", models.CharField(max_length=128, unique=True)),
                ("scopes", models.JSONField(blank=True, default=list)),
                ("is_active", models.BooleanField(default=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="api_keys", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="ExportPreset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=64)),
                ("filters", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="export_presets", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={"ordering": ["name"], "unique_together": {("user", "name")}},
        ),
        migrations.CreateModel(
            name="WebhookEndpoint",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=128)),
                ("target_url", models.URLField(max_length=500)),
                ("signing_secret", models.CharField(max_length=128)),
                ("subscribed_events", models.JSONField(blank=True, default=list)),
                ("is_active", models.BooleanField(default=True)),
                ("failure_count", models.PositiveIntegerField(default=0)),
                ("last_sent_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True)),
                ("timeout_seconds", models.PositiveIntegerField(default=10)),
                ("max_retries", models.PositiveIntegerField(default=2)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="webhook_endpoints", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={"ordering": ["name", "id"]},
        ),
        migrations.CreateModel(
            name="VendorProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("vendor_key", models.CharField(max_length=255, unique=True)),
                ("display_name", models.CharField(blank=True, max_length=512)),
                ("date_format_hint", models.CharField(blank=True, max_length=32)),
                ("tax_label_hint", models.CharField(blank=True, max_length=64)),
                ("extraction_hints", models.JSONField(blank=True, default=dict)),
                ("correction_count", models.PositiveIntegerField(default=0)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "default_category",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="vendor_profiles", to="documents.category"),
                ),
            ],
            options={"ordering": ["vendor_key"]},
        ),
        migrations.AddIndex(
            model_name="invoicedocument",
            index=models.Index(fields=["uploaded_by", "is_duplicate", "-upload_date"], name="documents_i_upload__703af5_idx"),
        ),
        migrations.AddIndex(
            model_name="invoicedocument",
            index=models.Index(fields=["uploaded_by", "duplicate_group"], name="documents_i_upload__79386a_idx"),
        ),
    ]
