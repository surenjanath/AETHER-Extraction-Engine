from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from django.utils import timezone as dj_timezone

from documents.models import InvoiceDocument, WebhookEndpoint
from documents.services.runtime_ollama import load_ollama_runtime

logger = logging.getLogger(__name__)


def emit_document_event(event: str, document: InvoiceDocument, extra: dict | None = None) -> None:
    settings = load_ollama_runtime()
    if not settings.enable_webhooks:
        return
    payload = {
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "document": {
            "id": document.pk,
            "status": document.status,
            "filename": document.original_filename,
            "is_duplicate": document.is_duplicate,
            "duplicate_group": document.duplicate_group,
            "duplicate_reason": document.duplicate_reason,
            "confidence_score": document.confidence_score,
            "extraction_error": document.extraction_error,
        },
    }
    if extra:
        payload["meta"] = extra
    endpoints = WebhookEndpoint.objects.filter(is_active=True)
    for endpoint in endpoints:
        subscribed = endpoint.subscribed_events or []
        if subscribed and event not in subscribed:
            continue
        _deliver(endpoint, payload)


def _deliver(endpoint: WebhookEndpoint, payload: dict) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(
        endpoint.signing_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    req = urllib.request.Request(
        endpoint.target_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-OfflineReceipt-Signature": f"sha256={signature}",
            "X-OfflineReceipt-Event": payload["event"],
        },
    )
    attempts = max(1, endpoint.max_retries + 1)
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=endpoint.timeout_seconds) as resp:
                if 200 <= resp.status < 300:
                    endpoint.last_sent_at = dj_timezone.now()
                    endpoint.last_error = ""
                    endpoint.failure_count = 0
                    endpoint.save(update_fields=["last_sent_at", "last_error", "failure_count"])
                    return
                last_error = f"http_status_{resp.status}"
        except urllib.error.URLError as exc:
            last_error = str(exc)
        if attempt < attempts:
            time.sleep(min(2 ** (attempt - 1), 5))
    endpoint.failure_count += 1
    endpoint.last_error = last_error[:1000]
    endpoint.save(update_fields=["failure_count", "last_error"])
    logger.warning("Webhook delivery failed endpoint=%s error=%s", endpoint.pk, last_error)

