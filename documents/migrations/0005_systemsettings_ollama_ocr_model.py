import os

from django.db import migrations, models


def seed_ocr_model_from_env(apps, schema_editor):
    SystemSettings = apps.get_model("documents", "SystemSettings")
    ocr = (os.environ.get("OLLAMA_OCR_MODEL") or "").strip()
    if ocr:
        SystemSettings.objects.filter(pk=1).update(ollama_ocr_model=ocr)


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0004_extractionlog"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsettings",
            name="ollama_ocr_model",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional: model for plain-text OCR from images (e.g. glm-ocr:latest). When set, OCR uses this model instead of the vision model and does not require vision_model_supports_vision. Leave blank to OCR with the vision model.",
                max_length=256,
            ),
        ),
        migrations.RunPython(seed_ocr_model_from_env, migrations.RunPython.noop),
    ]
