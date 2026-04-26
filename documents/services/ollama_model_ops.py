"""Ollama model discovery and capability inference helpers."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from documents.services.ollama_http import ollama_error_detail_from_response
from documents.services.runtime_ollama import get_model_server_base_url

logger = logging.getLogger(__name__)

_VISION_NAME_HINTS = re.compile(
    r"(llava|bakllava|moondream|minicpm-v|qwen.*vl|llama3\.2-vision|"
    r"llama-3\.2-vision|pixtral|granite-vision|glm-ocr|vision|gemma.*it.*vision|"
    r"gemma3.*it|multimodal)",
    re.IGNORECASE,
)


def _heuristic_vision_from_name(model_name: str) -> bool:
    if not model_name:
        return False
    return bool(_VISION_NAME_HINTS.search(model_name))


def _normalize_capabilities(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw.lower()] if raw else []
    if isinstance(raw, (list, tuple)):
        return [str(x).lower() for x in raw if x is not None]
    return []


def infer_capabilities(
    show_payload: dict[str, Any],
    model_name: str,
) -> tuple[bool, bool, list[str]]:
    """
    From /api/show JSON, return (supports_vision, supports_tools, caps_list).
    Falls back to model-name heuristics for vision when API omits capabilities.
    """
    caps = _normalize_capabilities(show_payload.get("capabilities"))
    meta = show_payload.get("meta") if isinstance(show_payload.get("meta"), dict) else {}
    modalities = _normalize_capabilities(meta.get("modalities")) if meta else []
    if modalities:
        caps.extend(x for x in modalities if x not in caps)

    has_vision = "vision" in caps or "image" in caps or "multimodal" in caps
    has_tools = "tools" in caps

    if not has_vision:
        has_vision = _heuristic_vision_from_name(model_name)

    return has_vision, has_tools, caps


def _fetch_tags_models(base_url: str, timeout: float = 15.0) -> list[dict[str, Any]]:
    base = (base_url or "").rstrip("/")
    url = f"{base}/api/tags"
    with httpx.Client(timeout=timeout) as client:
        r = client.get(url)
    if r.status_code >= 400:
        detail = ollama_error_detail_from_response(r)
        raise RuntimeError(
            f"Ollama /api/tags HTTP {r.status_code}: {detail}"
        ) from None
    payload = r.json()
    rows = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def ollama_show(base_url: str, model_name: str, timeout: float = 60.0) -> dict[str, Any]:
    """
    Return model metadata from Ollama `/api/show`.
    """
    wanted = (model_name or "").strip()
    if not wanted:
        raise RuntimeError("model_name is required")
    base = (base_url or "").rstrip("/")
    url = f"{base}/api/show"
    payload = {"model": wanted}
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json=payload)
    if r.status_code >= 400:
        detail = ollama_error_detail_from_response(r)
        raise RuntimeError(f"Ollama /api/show HTTP {r.status_code}: {detail}") from None
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError("Invalid response from /api/show")
    return data


def ollama_pull_sync(base_url: str, model_name: str, timeout: float = 900.0) -> tuple[bool, str]:
    """Pull model into Ollama synchronously via /api/pull."""
    base = (base_url or "").rstrip("/")
    wanted = (model_name or "").strip()
    if not wanted:
        return False, "model_name is required"
    url = f"{base}/api/pull"
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json={"model": wanted, "stream": False})
    if r.status_code >= 400:
        detail = ollama_error_detail_from_response(r)
        return False, f"Ollama /api/pull HTTP {r.status_code}: {detail}"
    return True, f"pulled: {wanted}"


def ollama_tags_full(base_url: str, timeout: float = 15.0) -> list[dict[str, Any]]:
    return _fetch_tags_models(base_url, timeout=timeout)


def refresh_capabilities_after_save(instance: Any) -> None:
    """Re-run model discovery for both configured models; update capability flags."""
    from documents.models import SystemSettings

    if not isinstance(instance, SystemSettings):
        return
    base_text = get_model_server_base_url("text", instance)
    base_vision = get_model_server_base_url("vision", instance)
    try:
        v_show = ollama_show(base_vision, instance.ollama_vision_model)
        v_vis, _, _ = infer_capabilities(v_show, instance.ollama_vision_model)
    except Exception as exc:
        logger.warning("Vision model show failed: %s", exc)
        v_vis = _heuristic_vision_from_name(instance.ollama_vision_model)
    try:
        t_show = ollama_show(base_text, instance.ollama_text_model)
        _, t_tools, _ = infer_capabilities(t_show, instance.ollama_text_model)
    except Exception as exc:
        logger.warning("Text model show failed: %s", exc)
        t_tools = False

    SystemSettings.objects.filter(pk=instance.pk).update(
        vision_model_supports_vision=v_vis,
        text_model_supports_tools=t_tools,
    )
