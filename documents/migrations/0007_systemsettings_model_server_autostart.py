from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0006_alter_systemsettings_ollama_ocr_model"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsettings",
            name="auto_start_model_server",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "When enabled, the app will try to start llama-server automatically "
                    "if the configured base URL is unreachable."
                ),
            ),
        ),
        migrations.AddField(
            model_name="systemsettings",
            name="model_server_start_command",
            field=models.TextField(
                blank=True,
                default="",
                help_text=(
                    "Command used to start llama-server (examples: "
                    "`llama-server --model C:\\models\\model.gguf --host 127.0.0.1 --port 11434 --mmap --mlock` "
                    "or `llama-server --hf-repo ggml-org/gemma-3-4b-it-GGUF:Q4_K_M --host 127.0.0.1 --port 11434 --mmap --mlock`)."
                ),
            ),
        ),
        migrations.AddField(
            model_name="systemsettings",
            name="model_server_start_timeout_seconds",
            field=models.PositiveIntegerField(
                default=45,
                help_text="How long to wait for llama-server to become reachable after startup.",
            ),
        ),
    ]
