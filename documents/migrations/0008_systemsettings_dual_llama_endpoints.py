from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0007_systemsettings_model_server_autostart"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsettings",
            name="text_model_base_url",
            field=models.CharField(
                default="http://127.0.0.1:11434",
                help_text="llama.cpp base URL for text model inference.",
                max_length=512,
            ),
        ),
        migrations.AddField(
            model_name="systemsettings",
            name="vision_model_base_url",
            field=models.CharField(
                default="http://127.0.0.1:11435",
                help_text="llama.cpp base URL for vision/OCR model inference.",
                max_length=512,
            ),
        ),
        migrations.AddField(
            model_name="systemsettings",
            name="text_model_server_start_command",
            field=models.TextField(
                blank=True,
                default="",
                help_text=(
                    "Command to start the text model llama-server instance "
                    "(typically on text_model_base_url)."
                ),
            ),
        ),
        migrations.AddField(
            model_name="systemsettings",
            name="vision_model_server_start_command",
            field=models.TextField(
                blank=True,
                default="",
                help_text=(
                    "Command to start the vision/OCR llama-server instance "
                    "(typically on vision_model_base_url)."
                ),
            ),
        ),
    ]
