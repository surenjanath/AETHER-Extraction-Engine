"""HTTP client for local Ollama server with JSON extraction retries."""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any, Optional

import httpx
from pydantic import ValidationError

from documents.services.ollama_http import (
    is_retryable_ollama_http_status,
    ollama_error_detail_from_response,
)
from documents.models import AIRuntimeLog
from documents.services.ai_runtime_log import append_ai_runtime_log
from documents.services.runtime_ollama import get_model_server_base_url, load_ollama_runtime
from documents.services.schema import EXTRACTION_JSON_INSTRUCTIONS, ExtractionSchema
from documents.services.text_extract import vision_png_size_candidates

logger = logging.getLogger(__name__)


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return text


def _isolate_json_object(s: str) -> str:
    """Take the first top-level `{ ... }` block; models often prefix/suffix prose."""
    s = s.strip()
    start = s.find("{")
    if start < 0:
        return s
    depth = 0
    for i, ch in enumerate(s[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return s[start:]


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = _isolate_json_object(_strip_json_fences(text))
    try:
        out = json.loads(cleaned)
    except json.JSONDecodeError:
        try:
            import json5

            out = json5.loads(cleaned)
        except Exception as exc:
            raise json.JSONDecodeError(
                f"invalid JSON (after brace isolation; json5 fallback failed: {exc})",
                cleaned,
                0,
            ) from exc
    if not isinstance(out, dict):
        raise json.JSONDecodeError("root JSON value must be an object", cleaned, 0)
    return out


def call_ollama_generate(
    model: str,
    prompt: str,
    images_b64: Optional[list[str]] = None,
    timeout: float = 180.0,
    base_url: Optional[str] = None,
    role: str = "text",
) -> str:
    """
    Backward-compatible wrapper name.

    Requests are sent to Ollama `/api/generate`.
    """
    base = (base_url or "").rstrip("/")
    if not base:
        base = get_model_server_base_url(role, load_ollama_runtime())
    started = time.perf_counter()
    url = f"{base}/api/generate"
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if images_b64:
        payload["images"] = images_b64

    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, json=payload)
    except httpx.RequestError as exc:
        append_ai_runtime_log(
            role=role,
            event="request_transport_error",
            level=AIRuntimeLog.Level.ERROR,
            model=model,
            base_url=base,
            latency_ms=int((time.perf_counter() - started) * 1000),
            message=str(exc),
        )
        raise

    try:
        data = r.json()
    except (ValueError, json.JSONDecodeError, TypeError):
        data = {}

    if r.status_code >= 400:
        detail = ollama_error_detail_from_response(r)
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict) and err.get("message"):
            detail = str(err["message"]).strip()
        elif err:
            detail = str(err).strip()
        append_ai_runtime_log(
            role=role,
            event="request_http_error",
            level=AIRuntimeLog.Level.ERROR,
            model=model,
            base_url=base,
            latency_ms=int((time.perf_counter() - started) * 1000),
            message=detail,
            details={"status_code": r.status_code},
        )
        raise httpx.HTTPStatusError(
            f"{r.status_code} {detail}",
            request=r.request,
            response=r,
        )

    if isinstance(data, dict) and data.get("error"):
        append_ai_runtime_log(
            role=role,
            event="request_model_error",
            level=AIRuntimeLog.Level.ERROR,
            model=model,
            base_url=base,
            latency_ms=int((time.perf_counter() - started) * 1000),
            message=str(data["error"]),
        )
        raise RuntimeError(f"Ollama /api/generate: {data['error']}")

    out = data.get("response") if isinstance(data, dict) else None
    if not isinstance(out, str):
        append_ai_runtime_log(
            role=role,
            event="request_empty",
            level=AIRuntimeLog.Level.WARNING,
            model=model,
            base_url=base,
            latency_ms=int((time.perf_counter() - started) * 1000),
            message="empty response from model",
        )
        return ""
    append_ai_runtime_log(
        role=role,
        event="request_ok",
        model=model,
        base_url=base,
        latency_ms=int((time.perf_counter() - started) * 1000),
        message="response received",
    )
    return out.strip()


OCR_PLAIN_PROMPT = """Transcribe all visible printed text on this receipt or invoice image.
Preserve line breaks roughly where lines break on the paper.
Output plain text only: no markdown fences, no JSON, no commentary before or after the text."""


def ocr_image_with_ollama(
    image_bytes: bytes,
    *,
    model: str,
    base_url: Optional[str] = None,
    max_attempts_per_variant: int = 2,
    timeout: float = 180.0,
) -> str:
    """
    Plain-text OCR via the same Ollama vision /api/generate path used for structured extraction.

    Retries with smaller PNGs on HTTP 5xx (VRAM / model load), matching ``extract_with_retries``.
    Returns empty string if every attempt fails or the model returns only whitespace.
    """
    if not image_bytes:
        return ""

    variants = vision_png_size_candidates(image_bytes)
    errors: list[str] = []
    prompt = OCR_PLAIN_PROMPT

    for img in variants:
        images_b64 = [base64.b64encode(img).decode("ascii")]
        tag = f"{len(img)}b"
        inner_prompt = prompt
        for attempt in range(1, max_attempts_per_variant + 1):
            try:
                text = call_ollama_generate(
                    model,
                    inner_prompt,
                    images_b64=images_b64,
                    timeout=timeout,
                    base_url=base_url,
                    role="vision",
                )
                if text.strip():
                    if img is not variants[0]:
                        logger.info(
                            "Ollama OCR succeeded with downscaled image (%s, model=%s)",
                            tag,
                            model,
                        )
                    return text
                msg = f"ocr {tag} attempt {attempt}: empty model response"
                errors.append(msg)
                logger.info("Ollama OCR retry: %s", msg)
                inner_prompt = (
                    f"{OCR_PLAIN_PROMPT}\n\nYour previous reply was empty or whitespace only. "
                    "Transcribe every legible line from the image again."
                )
            except httpx.HTTPStatusError as exc:
                resp = exc.response
                sc = resp.status_code if resp is not None else 0
                detail = (
                    ollama_error_detail_from_response(resp)
                    if resp is not None
                    else str(exc)
                )
                msg = f"ocr {tag} attempt {attempt}: HTTP {sc}: {detail}"
                errors.append(msg)
                logger.info("Ollama OCR HTTP issue: %s", msg)
                if (
                    resp is not None
                    and is_retryable_ollama_http_status(sc)
                    and img is not variants[-1]
                ):
                    break
                break
            except httpx.RequestError as exc:
                msg = f"ocr {tag} attempt {attempt}: {exc}"
                errors.append(msg)
                logger.warning("Ollama OCR transport error: %s", msg)
                return ""

    if errors:
        logger.warning("Ollama OCR exhausted retries: %s", "; ".join(errors[:8]))
    return ""


def extract_with_retries(
    prompt: str,
    model: str,
    image_bytes: Optional[bytes] = None,
    max_attempts: int = 3,
    base_url: Optional[str] = None,
) -> tuple[ExtractionSchema, str, list[str]]:
    """
    Returns (schema, raw_response_text, attempt_errors).

    For vision, on HTTP 500/502/503 (often VRAM / model load), retries with smaller PNGs
    before giving up. Malformed JSON from the model is retried with the same image.
    """
    image_variants: list[Optional[bytes]]
    if image_bytes:
        image_variants = vision_png_size_candidates(image_bytes)
    else:
        image_variants = [None]

    errors: list[str] = []
    last_response = ""

    for img in image_variants:
        images_b64: Optional[list[str]] = None
        if img is not None:
            images_b64 = [base64.b64encode(img).decode("ascii")]
        tag = f"{len(img)}b" if img is not None else "text"

        conversation = prompt + "\n\n" + EXTRACTION_JSON_INSTRUCTIONS

        for attempt in range(1, max_attempts + 1):
            try:
                last_response = call_ollama_generate(
                    model,
                    conversation,
                    images_b64=images_b64,
                    base_url=base_url,
                    role="vision" if images_b64 else "text",
                )
                obj = _parse_json_object(last_response)
                parsed = ExtractionSchema.model_validate(obj)
                if img is not image_variants[0] and image_bytes:
                    logger.info(
                        "Ollama vision succeeded with downscaled image (%s, model=%s)",
                        tag,
                        model,
                    )
                return parsed, last_response, errors
            except httpx.HTTPStatusError as exc:
                resp = exc.response
                sc = resp.status_code if resp is not None else 0
                detail = (
                    ollama_error_detail_from_response(resp)
                    if resp is not None
                    else str(exc)
                )
                msg = f"image {tag} attempt {attempt}: HTTP {sc}: {detail}"
                errors.append(msg)
                logger.info("Ollama extraction HTTP issue: %s", msg)
                if (
                    resp is not None
                    and is_retryable_ollama_http_status(sc)
                    and img is not None
                    and img is not image_variants[-1]
                ):
                    break
                raise RuntimeError(msg) from exc
            except httpx.RequestError as exc:
                msg = f"image {tag} attempt {attempt}: {exc}"
                errors.append(msg)
                raise RuntimeError(msg) from exc
            except (json.JSONDecodeError, ValidationError, RuntimeError) as exc:
                msg = f"image {tag} attempt {attempt}: {exc}"
                errors.append(msg)
                logger.info("Ollama extraction retry: %s", msg)
                conversation = (
                    f"{prompt}\n\nPrevious invalid output:\n{last_response}\n\n"
                    f"Errors: {exc}\n\nReturn ONLY valid JSON matching the schema.\n"
                    f"{EXTRACTION_JSON_INSTRUCTIONS}"
                )

    raise RuntimeError("; ".join(errors) if errors else "extraction failed")
