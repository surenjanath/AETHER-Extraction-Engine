"""Load Ollama-related configuration from the database (singleton SystemSettings)."""

from __future__ import annotations

from documents.models import SystemSettings


def load_ollama_runtime() -> SystemSettings:
    """Return the single settings row (creates row with defaults if missing)."""
    obj, _ = SystemSettings.objects.get_or_create(pk=1)
    return obj


def get_model_server_base_url(role: str, settings: SystemSettings | None = None) -> str:
    """
    Resolve Ollama base URL (single process/server).
    """
    s = settings or load_ollama_runtime()
    _ = role
    return (s.ollama_base_url or "").strip().rstrip("/")
