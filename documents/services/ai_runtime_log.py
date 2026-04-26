"""Persistence helpers for AI runtime logs."""

from __future__ import annotations

from typing import Any

from documents.models import AIRuntimeLog


def append_ai_runtime_log(
    *,
    role: str,
    event: str,
    level: str = AIRuntimeLog.Level.INFO,
    model: str = "",
    base_url: str = "",
    latency_ms: int | None = None,
    message: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    try:
        AIRuntimeLog.objects.create(
            role=(role or "").strip()[:16] or "text",
            event=(event or "").strip()[:64] or "event",
            level=level if level in AIRuntimeLog.Level.values else AIRuntimeLog.Level.INFO,
            model=(model or "")[:255],
            base_url=(base_url or "")[:512],
            latency_ms=latency_ms,
            message=message or "",
            details=details or None,
        )
    except Exception:
        # Logging must never break inference flow.
        return
