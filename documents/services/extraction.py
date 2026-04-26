"""Orchestrate file → Ollama → DB → audit → category for one InvoiceDocument."""

from __future__ import annotations

import logging
from pathlib import Path
from decimal import Decimal
from datetime import datetime
import re

from django.db import transaction

from documents.models import (
    DocumentStatus,
    ExtractedData,
    InvoiceDocument,
    LineItem,
    SystemSettings,
)
from documents.services.audit import run_deterministic_audit
from documents.services.categorization import assign_category, heuristic_confidence
from documents.services.extraction_logging import append_extraction_log
from documents.services.ollama_client import extract_with_retries
from documents.services.runtime_ollama import get_model_server_base_url, load_ollama_runtime
from documents.services.prompt_hints import build_correction_hints
from documents.services.schema import EXTRACTION_JSON_INSTRUCTIONS
from documents.services.receipt_text import (
    DEFAULT_EXTRACTION_TEXT_BUDGET,
    prepare_receipt_text_for_llm,
)
from documents.services.text_extract import (
    extract_text_from_pdf,
    ocr_image_bytes,
    pdf_first_page_as_png_bytes,
)

logger = logging.getLogger(__name__)

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
PDF_EXT = {".pdf"}


def _suffix(name: str) -> str:
    return Path(name.lower()).suffix


def _resolved_ocr_model(rt: SystemSettings) -> str:
    """Dedicated OCR model (e.g. glm-ocr:latest) or the vision model when unset."""
    ocr = (getattr(rt, "ollama_ocr_model", None) or "").strip()
    return ocr or (rt.ollama_vision_model or "").strip()


def _model_name_is_ocr_tuned(model_name: str) -> bool:
    """
    True for models that are built for transcription / OCR, not schema JSON.

    Those models work in the Ollama UI for "read this image", but they must not
    receive the structured extraction prompt (they return prose, markdown, or
    Python-ish dicts that are not strict JSON).
    """
    n = (model_name or "").strip().lower()
    if not n:
        return False
    needles = (
        "glm-ocr",
        "deepseek-ocr",
        "paddleocr",
        "trocr",
        "doc-ocr",
        "ocr-v",
    )
    return any(s in n for s in needles)


def _ocr_skip_capability_gate(rt: SystemSettings) -> bool:
    """
    Allow Ollama /images OCR when:
    - a dedicated OCR model is configured, or
    - the vision slot uses an OCR-tuned model (e.g. glm-ocr:latest) so /api/show
      may omit 'vision' even though /api/generate accepts images.
    """
    if bool((getattr(rt, "ollama_ocr_model", None) or "").strip()):
        return True
    return _model_name_is_ocr_tuned(rt.ollama_vision_model or "")


def _build_prompt_from_text(ocr_or_pdf_text: str, hints: str) -> str:
    body = prepare_receipt_text_for_llm(
        ocr_or_pdf_text, budget=DEFAULT_EXTRACTION_TEXT_BUDGET
    )
    base = (
        "You extract structured invoice/receipt data from the following text "
        "(possibly dense OCR from a photographed or scanned receipt).\n\n"
        "Critical: prioritize accurate subtotal/tax/total fields. "
        "Only include line_items that clearly exist with readable amounts. "
        "If line items are noisy, return an empty line_items array.\n\n"
        f"--- DOCUMENT TEXT ---\n{body}\n--- END ---\n\n"
    )
    if hints:
        base += hints + "\n\n"
    return base + EXTRACTION_JSON_INSTRUCTIONS


def _build_prompt_vision(hints: str) -> str:
    base = (
        "You are reading a receipt/invoice image (may be crumpled, skewed, or low contrast). "
        "Extract structured data; read printed SUBTOTAL, TAX, and TOTAL amounts carefully. "
        "Do not invent line items: if uncertain, return fewer lines or empty line_items.\n\n"
    )
    if hints:
        base += hints + "\n\n"
    return base + EXTRACTION_JSON_INSTRUCTIONS


def _cleanup_line_items(parsed) -> None:
    """
    Remove obviously noisy line_items to improve deterministic audit reliability.
    Keeps totals as source of truth when line rows are low-confidence OCR output.
    """
    if not parsed.line_items:
        return

    clean_lines = []
    total_cap = parsed.total_amount or parsed.subtotal
    for li in parsed.line_items:
        desc = (li.description or "").strip()
        if not desc:
            continue
        if len(desc) < 2:
            continue
        line_total = li.line_total
        if line_total is None:
            continue
        if line_total < Decimal("0"):
            continue
        if total_cap is not None and line_total > (total_cap * Decimal("1.5")):
            # Impossible per-line amount for this receipt.
            continue
        clean_lines.append(li)

    parsed.line_items = clean_lines

    if parsed.subtotal is None or not parsed.line_items:
        return

    line_sum = sum((li.line_total or Decimal("0")) for li in parsed.line_items)
    drift = abs(line_sum - parsed.subtotal)

    # If OCR line rows are clearly unreliable, drop them and trust printed totals.
    if len(parsed.line_items) >= 8 and drift > Decimal("2.00"):
        parsed.line_items = []
    elif len(parsed.line_items) >= 4 and drift > (parsed.subtotal * Decimal("0.25")):
        parsed.line_items = []


def _infer_date_from_text(ocr_text: str):
    """
    Deterministic fallback date extraction from OCR text.
    Prioritizes explicit `Date:` labels, then broader date patterns.
    """
    text = (ocr_text or "").strip()
    if not text:
        return None

    candidates: list[str] = []
    labeled = re.findall(
        r"(?i)\bdate\b\s*[:\-]?\s*([0-9]{1,4}[\/\-][0-9]{1,2}[\/\-][0-9]{1,4})",
        text,
    )
    candidates.extend(labeled)
    if not candidates:
        general = re.findall(r"\b([0-9]{1,4}[\/\-][0-9]{1,2}[\/\-][0-9]{1,4})\b", text)
        candidates.extend(general[:8])

    for raw in candidates:
        token = raw.strip()
        for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m-%d-%y", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                parsed = datetime.strptime(token, fmt).date()
                if 2000 <= parsed.year <= 2100:
                    return parsed
            except ValueError:
                continue
    return None


def _infer_document_type_from_text(raw_text: str) -> str:
    text = (raw_text or "").lower()
    if not text:
        return "unknown"
    invoice_hits = sum(
        1
        for token in ("invoice", "invoice no", "inv #", "bill to", "due date")
        if token in text
    )
    receipt_hits = sum(
        1
        for token in ("receipt", "change", "cashier", "tender", "thank you")
        if token in text
    )
    if invoice_hits > receipt_hits and invoice_hits > 0:
        return "invoice"
    if receipt_hits > invoice_hits and receipt_hits > 0:
        return "receipt"
    return "unknown"


def _infer_invoice_number_from_text(raw_text: str) -> str:
    text = raw_text or ""
    patterns = [
        r"(?im)\b(?:invoice|inv)\s*(?:no|number|#)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-\/]{1,40})\b",
        r"(?im)\bbill\s*(?:no|number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-\/]{1,40})\b",
    ]
    for pat in patterns:
        match = re.search(pat, text)
        if match:
            token = (match.group(1) or "").strip()
            # Avoid accidental captures like location/vendor words ("East", "Store").
            if (
                token
                and len(token) <= 80
                and (
                    re.search(r"\d", token) is not None
                    or "-" in token
                    or "/" in token
                )
            ):
                return token
    return ""


def run_extraction_for_document(document_id: int) -> None:
    doc = InvoiceDocument.objects.select_related("uploaded_by").get(pk=document_id)
    path = Path(doc.file.path)
    suffix = _suffix(doc.original_filename or path.name)
    rt = load_ollama_runtime()
    base_text = get_model_server_base_url("text", rt)
    base_vision = get_model_server_base_url("vision", rt)

    append_extraction_log(
        document_id,
        "info",
        f"Pipeline started: {doc.original_filename or path.name}",
        event="extraction_started",
        details={
            "suffix": suffix,
            "text_base": base_text,
            "vision_base": base_vision,
            "use_vision": rt.use_vision_extraction,
            "vision_capable": rt.vision_model_supports_vision,
            "text_model": rt.ollama_text_model,
            "vision_model": rt.ollama_vision_model,
            "ocr_model": _resolved_ocr_model(rt),
            "dedicated_ocr": _ocr_skip_capability_gate(rt),
        },
    )

    hints = build_correction_hints()
    vision_prompt = _build_prompt_vision(hints)
    text_for_model = ""
    image_bytes: bytes | None = None
    model_used = rt.ollama_text_model
    try:
        if suffix in PDF_EXT:
            append_extraction_log(
                document_id,
                "info",
                "Detected PDF; extracting embedded text and optional first-page raster.",
                event="pdf_detected",
            )
            text_for_model = extract_text_from_pdf(path)
            append_extraction_log(
                document_id,
                "info",
                f"PDF text layer length: {len(text_for_model)} chars.",
                event="pdf_text_extracted",
                details={"chars": len(text_for_model)},
            )
            # Rasterize page 1 for vision and/or OCR when the PDF has no usable text (scanned PDFs).
            want_vision_raster = (
                rt.use_vision_extraction and rt.vision_model_supports_vision
            )
            want_ocr_raster = not text_for_model.strip()
            if want_vision_raster or want_ocr_raster:
                try:
                    image_bytes = pdf_first_page_as_png_bytes(path)
                    append_extraction_log(
                        document_id,
                        "info",
                        f"First page rasterized ({len(image_bytes)} bytes) for "
                        f"{'vision+OCR' if want_vision_raster and want_ocr_raster else 'vision' if want_vision_raster else 'OCR fallback'}.",
                        event="pdf_raster_ok",
                        details={
                            "png_bytes": len(image_bytes),
                            "vision_raster": want_vision_raster,
                            "ocr_fallback_raster": want_ocr_raster,
                        },
                    )
                except Exception as exc:
                    logger.warning("PDF rasterize failed: %s", exc)
                    append_extraction_log(
                        document_id,
                        "warning",
                        f"PDF rasterize failed: {exc}",
                        event="pdf_raster_failed",
                    )
        elif suffix in IMAGE_EXT:
            append_extraction_log(
                document_id,
                "info",
                "Detected image receipt; loading bytes for vision/OCR.",
                event="image_detected",
            )
            image_bytes = path.read_bytes()
            if not (rt.use_vision_extraction and rt.vision_model_supports_vision):
                text_for_model = ocr_image_bytes(
                    image_bytes,
                    ollama_model=_resolved_ocr_model(rt),
                    ollama_base_url=base_vision,
                    vision_capable=rt.vision_model_supports_vision,
                    skip_capability_gate=_ocr_skip_capability_gate(rt),
                )
                append_extraction_log(
                    document_id,
                    "info",
                    f"Ollama OCR (no structured vision path): {len(text_for_model)} chars.",
                    event="image_ocr",
                    details={"chars": len(text_for_model)},
                )
        else:
            append_extraction_log(
                document_id,
                "info",
                f"Generic file suffix {suffix!r}; attempting read as image + OCR.",
                event="generic_file",
            )
            # generic binary: try as image
            try:
                image_bytes = path.read_bytes()
                text_for_model = ocr_image_bytes(
                    image_bytes,
                    ollama_model=_resolved_ocr_model(rt),
                    ollama_base_url=base_vision,
                    vision_capable=rt.vision_model_supports_vision,
                    skip_capability_gate=_ocr_skip_capability_gate(rt),
                )
            except Exception:
                text_for_model = ""

        parsed = None
        raw_response = ""
        errors: list[str] = []
        vision_attempted = False

        structured_vision_model = not _model_name_is_ocr_tuned(rt.ollama_vision_model or "")
        use_vision_path = (
            rt.use_vision_extraction
            and rt.vision_model_supports_vision
            and image_bytes
            and structured_vision_model
        )
        if (
            rt.use_vision_extraction
            and rt.vision_model_supports_vision
            and image_bytes
            and not structured_vision_model
        ):
            append_extraction_log(
                document_id,
                "info",
                f"Skipping structured JSON vision: {rt.ollama_vision_model!r} is an OCR-tuned "
                "model (plain text). Using OCR + text model instead — same as chatting in Ollama.",
                event="vision_skipped_ocr_tuned_model",
            )
        if use_vision_path:
            vision_attempted = True
            append_extraction_log(
                document_id,
                "info",
                f"Calling Ollama vision model {rt.ollama_vision_model!r}.",
                event="ollama_vision_attempt",
            )
            try:
                parsed, raw_response, errors = extract_with_retries(
                    vision_prompt,
                    rt.ollama_vision_model,
                    image_bytes=image_bytes,
                    max_attempts=3,
                    base_url=base_vision,
                )
                model_used = rt.ollama_vision_model
                append_extraction_log(
                    document_id,
                    "info",
                    "Vision model returned structured JSON.",
                    event="ollama_vision_ok",
                    details={
                        "model": model_used,
                        "retry_errors": errors[:5],
                        "raw_chars": len(raw_response or ""),
                    },
                )
            except Exception as exc:
                logger.warning("Vision extraction failed, falling back to text: %s", exc)
                append_extraction_log(
                    document_id,
                    "warning",
                    f"Vision extraction failed, using text path: {exc}",
                    event="ollama_vision_failed",
                )
                parsed = None

        if parsed is None:
            if not text_for_model.strip() and image_bytes:
                text_for_model = ocr_image_bytes(
                    image_bytes,
                    ollama_model=_resolved_ocr_model(rt),
                    ollama_base_url=base_vision,
                    vision_capable=rt.vision_model_supports_vision,
                    skip_capability_gate=_ocr_skip_capability_gate(rt),
                )
                append_extraction_log(
                    document_id,
                    "info",
                    f"Ollama OCR before text model: {len(text_for_model)} chars.",
                    event="ocr_before_text_model",
                    details={"chars": len(text_for_model)},
                )
            if not text_for_model.strip():
                parts = [
                    "No usable input for the text model: PDF text layer empty or missing,",
                    "and Ollama OCR produced no text.",
                ]
                if vision_attempted:
                    parts.append(
                        "Vision was attempted but did not return valid JSON (see prior logs)."
                    )
                elif not (
                    rt.use_vision_extraction and rt.vision_model_supports_vision
                ):
                    parts.append(
                        "Vision is off or the vision model is not marked vision-capable in Settings;"
                        " OCR requires a reachable vision/OCR model server."
                    )
                if image_bytes:
                    parts.append(f"First-page raster exists ({len(image_bytes)} bytes) but OCR text is empty.")
                raise RuntimeError(" ".join(parts))
            append_extraction_log(
                document_id,
                "info",
                f"Calling Ollama text model {rt.ollama_text_model!r} on extracted text.",
                event="ollama_text_attempt",
                details={
                    "prompt_text_chars": min(
                        len(text_for_model), DEFAULT_EXTRACTION_TEXT_BUDGET
                    ),
                },
            )
            prompt = _build_prompt_from_text(text_for_model, hints)
            parsed, raw_response, errors = extract_with_retries(
                prompt,
                rt.ollama_text_model,
                image_bytes=None,
                max_attempts=3,
                base_url=base_text,
            )
            model_used = rt.ollama_text_model
            append_extraction_log(
                document_id,
                "info",
                "Text model returned structured JSON.",
                event="ollama_text_ok",
                details={
                    "model": model_used,
                    "retry_errors": errors[:5],
                    "raw_chars": len(raw_response or ""),
                },
            )

        _cleanup_line_items(parsed)
        if parsed.date_issued is None and text_for_model.strip():
            inferred_date = _infer_date_from_text(text_for_model)
            if inferred_date is not None:
                parsed.date_issued = inferred_date
                append_extraction_log(
                    document_id,
                    "info",
                    f"Backfilled date from OCR text: {inferred_date.isoformat()}",
                    event="date_backfilled_from_text",
                )
        fallback_text = text_for_model or ""
        if not fallback_text.strip() and image_bytes:
            try:
                fallback_text = ocr_image_bytes(
                    image_bytes,
                    ollama_model=_resolved_ocr_model(rt),
                    ollama_base_url=base_vision,
                    vision_capable=rt.vision_model_supports_vision,
                    skip_capability_gate=_ocr_skip_capability_gate(rt),
                )
                append_extraction_log(
                    document_id,
                    "info",
                    f"Secondary OCR for invoice/type fallback: {len(fallback_text)} chars.",
                    event="ocr_secondary_for_fallback",
                )
            except Exception as exc:
                append_extraction_log(
                    document_id,
                    "warning",
                    f"Secondary OCR fallback failed: {exc}",
                    event="ocr_secondary_for_fallback_failed",
                )
        if fallback_text.strip():
            if not parsed.invoice_number:
                inferred_invoice_no = _infer_invoice_number_from_text(fallback_text)
                if inferred_invoice_no:
                    parsed.invoice_number = inferred_invoice_no
                    append_extraction_log(
                        document_id,
                        "info",
                        f"Backfilled invoice number from OCR text: {inferred_invoice_no}",
                        event="invoice_number_backfilled_from_text",
                    )
            if (parsed.document_type or "unknown") == "unknown":
                parsed.document_type = _infer_document_type_from_text(fallback_text)
                append_extraction_log(
                    document_id,
                    "info",
                    f"Document type inferred from OCR text: {parsed.document_type}",
                    event="document_type_inferred",
                )

        with transaction.atomic():
            extracted, _ = ExtractedData.objects.update_or_create(
                document=doc,
                defaults={
                    "vendor_name": parsed.vendor_name or "",
                    "date_issued": parsed.date_issued,
                    "invoice_number": parsed.invoice_number or "",
                    "document_type": parsed.document_type or "unknown",
                    "subtotal": parsed.subtotal,
                    "tax_amount": parsed.tax_amount,
                    "total_amount": parsed.total_amount,
                    "raw_json": parsed.model_dump(mode="json"),
                    "ollama_model_used": model_used,
                },
            )
            extracted.line_items.all().delete()
            for i, li in enumerate(parsed.line_items):
                LineItem.objects.create(
                    extracted=extracted,
                    description=li.description or "",
                    quantity=li.quantity,
                    unit_price=li.unit_price,
                    line_total=li.line_total,
                    ordering=i,
                )

        extracted = ExtractedData.objects.prefetch_related("line_items").get(pk=extracted.pk)
        n_lines = extracted.line_items.count()
        append_extraction_log(
            document_id,
            "info",
            f"Persisted extraction: vendor={extracted.vendor_name!r}, lines={n_lines}, total={extracted.total_amount}.",
            event="persist_extracted",
            details={
                "vendor_name": (extracted.vendor_name or "")[:120],
                "line_items": n_lines,
                "ollama_model_used": extracted.ollama_model_used or model_used,
            },
        )
        audit = run_deterministic_audit(extracted)
        cat, _reason = assign_category(extracted)
        extracted.category = cat
        extracted.save(update_fields=["category"])

        has_cat = cat is not None
        conf = heuristic_confidence(audit, has_cat)

        if audit["all_ok"] and has_cat:
            new_status = DocumentStatus.VERIFIED
        else:
            new_status = DocumentStatus.AUDIT_REQUIRED

        doc.confidence_score = conf
        doc.status = new_status
        doc.extraction_error = "; ".join(audit["messages"]) if audit["messages"] else ""
        doc.save(update_fields=["confidence_score", "status", "extraction_error"])
        append_extraction_log(
            document_id,
            "warning" if new_status == DocumentStatus.AUDIT_REQUIRED else "info",
            f"Deterministic audit all_ok={audit['all_ok']}; category={getattr(cat, 'name', None)}; status={new_status}.",
            event="audit_complete",
            details={
                "all_ok": audit["all_ok"],
                "messages": audit["messages"][:12],
                "confidence": float(conf),
                "category": getattr(cat, "name", None),
                "document_status": new_status,
            },
        )
        append_extraction_log(
            document_id,
            "info",
            "Pipeline finished successfully.",
            event="extraction_finished",
        )

    except Exception as exc:
        logger.exception("Extraction failed for document %s", document_id)
        append_extraction_log(
            document_id,
            "error",
            str(exc),
            event="extraction_failed",
            details={"type": type(exc).__name__},
        )
        InvoiceDocument.objects.filter(pk=document_id).update(
            status=DocumentStatus.AUDIT_REQUIRED,
            extraction_error=str(exc)[:2000],
            confidence_score=0.0,
        )
