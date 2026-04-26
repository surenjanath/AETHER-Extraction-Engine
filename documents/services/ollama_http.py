"""Shared helpers for parsing Ollama HTTP responses."""

from __future__ import annotations

import json
from typing import Any

import httpx


def ollama_error_detail_from_response(response: httpx.Response) -> str:
    """Best-effort message from JSON `error` payloads or raw body (for 5xx / 4xx)."""
    try:
        data: Any = response.json()
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            if isinstance(err, dict) and err.get("message"):
                return str(err["message"]).strip()
            return str(err).strip()
    except (ValueError, json.JSONDecodeError, TypeError):
        pass
    text = (response.text or "").strip()
    if text:
        return text[:1200]
    return response.reason_phrase or f"HTTP {response.status_code}"


def is_retryable_ollama_http_status(status_code: int) -> bool:
    """Server / capacity errors where a smaller vision image may help."""
    return status_code in (500, 502, 503)
