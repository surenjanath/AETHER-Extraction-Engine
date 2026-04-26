import os

from django.db import migrations, models


def seed_system_settings(apps, schema_editor):
    SystemSettings = apps.get_model("documents", "SystemSettings")
    base = (os.environ.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
    vision = os.environ.get("OLLAMA_VISION_MODEL") or "llava:latest"
    text = os.environ.get("OLLAMA_TEXT_MODEL") or "llama3:latest"
    use_vis = os.environ.get("USE_VISION_EXTRACTION", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    SystemSettings.objects.update_or_create(
        pk=1,
        defaults={
            "ollama_base_url": base,
            "ollama_vision_model": vision,
            "ollama_text_model": text,
            "use_vision_extraction": use_vis,
            "vision_model_supports_vision": True,
            "text_model_supports_tools": False,
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0002_seed_categories"),
    ]

    operations = [
        migrations.CreateModel(
            name="SystemSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "ollama_base_url",
                    models.CharField(
                        default="http://127.0.0.1:11434",
                        help_text="Ollama API base URL (no trailing slash required).",
                        max_length=512,
                    ),
                ),
                (
                    "ollama_vision_model",
                    models.CharField(
                        default="llava:latest",
                        help_text="Model used for image / PDF page vision extraction.",
                        max_length=256,
                    ),
                ),
                (
                    "ollama_text_model",
                    models.CharField(
                        default="llama3:latest",
                        help_text="Model used for text-only JSON extraction.",
                        max_length=256,
                    ),
                ),
                (
                    "use_vision_extraction",
                    models.BooleanField(
                        default=True,
                        help_text="When True, try vision path first for images and PDFs if the vision model supports images.",
                    ),
                ),
                (
                    "vision_model_supports_vision",
                    models.BooleanField(
                        default=True,
                        help_text="Auto-detected: vision model accepts image input (/api/show capabilities or name heuristic).",
                    ),
                ),
                (
                    "text_model_supports_tools",
                    models.BooleanField(
                        default=False,
                        help_text="Auto-detected: text model exposes tools capability (for future tool use).",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "system settings",
                "verbose_name_plural": "system settings",
            },
        ),
        migrations.RunPython(seed_system_settings, migrations.RunPython.noop),
    ]
