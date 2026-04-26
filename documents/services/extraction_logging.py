"""Persist extraction pipeline events for operator visibility (and mirror to Python logging)."""

from __future__ import annotations

import logging
from typing import Any

from documents.models import ExtractionLog

_pipeline_logger = logging.getLogger("documents.extraction.pipeline")


def append_extraction_log(
    document_id: int,
    level: str,
    message: str,
    *,
    event: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    """
    Write one ExtractionLog row. Never raises — failures only go to root logging.
    """
    lvl = level if level in ("info", "warning", "error") else "info"
    msg = (message or "")[:8000]
    try:
        ExtractionLog.objects.create(
            document_id=document_id,
            level=lvl,
            event=(event or "")[:64],
            message=msg,
            details=details,
        )
    except Exception:
        logging.getLogger(__name__).exception(
            "append_extraction_log failed for document_id=%s", document_id
        )
        return

    log_fn = getattr(_pipeline_logger, lvl, _pipeline_logger.info)
    extra = ""
    if details:
        try:
            extra = " | " + str(details)[:500]
        except Exception:
            extra = ""
    log_fn("[doc=%s] %s%s", document_id, msg, extra)
