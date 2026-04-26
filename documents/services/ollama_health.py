"""Lightweight Ollama API reachability check (sync, short timeout)."""

from __future__ import annotations

from typing import Any

import httpx
from django.utils import timezone

from documents.services.runtime_ollama import get_model_server_base_url, load_ollama_runtime


def check_ollama_tags(
    timeout: float = 3.0,
    base_url: str | None = None,
    *,
    role: str = "text",
) -> dict[str, Any]:
    """
    GET {base}/api/tags — confirms Ollama is reachable.

    Returns dict: ok (bool), status_code (int|None), error (str|None),
    models_sample (list of str, first few names), checked_at (ISO UTC str).
    """
    if base_url is None:
        try:
            base_url = get_model_server_base_url(role, load_ollama_runtime())
        except Exception:
            base_url = ""
    base = (base_url or "").rstrip("/")
    checked_at = timezone.now().isoformat()
    if not base:
        return {
            "ok": False,
            "status_code": None,
            "error": "Ollama base URL is not configured in System settings",
            "models_sample": [],
            "checked_at": checked_at,
        }
    url = f"{base}/api/tags"
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(url)
    except httpx.TimeoutException:
        return {
            "ok": False,
            "status_code": None,
            "error": "Connection timed out",
            "models_sample": [],
            "checked_at": checked_at,
        }
    except httpx.RequestError as exc:
        return {
            "ok": False,
            "status_code": None,
            "error": str(exc) or "Request failed",
            "models_sample": [],
            "checked_at": checked_at,
        }

    if r.status_code != 200:
        return {
            "ok": False,
            "status_code": r.status_code,
            "error": r.text[:200] if r.text else f"HTTP {r.status_code}",
            "models_sample": [],
            "checked_at": checked_at,
        }

    names: list[str] = []
    try:
        data = r.json()
        for m in (data.get("models") or [])[:8]:
            if isinstance(m, dict) and m.get("name"):
                names.append(str(m["name"]))
    except Exception:
        pass

    return {
        "ok": True,
        "status_code": r.status_code,
        "error": None,
        "models_sample": names,
        "checked_at": checked_at,
    }
