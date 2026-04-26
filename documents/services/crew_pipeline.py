"""CrewAI-orchestrated extraction pipeline (Ollama-only backend)."""

from __future__ import annotations

import logging
import re
import time
from io import BytesIO
from decimal import Decimal
from pathlib import Path

from django.db import transaction
from PIL import Image

from documents.models import (
    DocumentStatus,
    ExtractedData,
    InvoiceDocument,
    LineItem,
)
from documents.services.audit import run_deterministic_audit
from documents.services.categorization import assign_category, heuristic_confidence
from documents.services.extraction import (
    IMAGE_EXT,
    PDF_EXT,
    _build_prompt_from_text,
    _build_prompt_vision,
    _cleanup_line_items,
    _infer_document_type_from_text,
    _infer_date_from_text,
    _infer_invoice_number_from_text,
    _model_name_is_ocr_tuned,
    _ocr_skip_capability_gate,
    _resolved_ocr_model,
    _suffix,
)
from documents.services.extraction_logging import append_extraction_log
from documents.services.ollama_client import extract_with_retries
from documents.services.prompt_hints import build_correction_hints
from documents.services.receipt_text import DEFAULT_EXTRACTION_TEXT_BUDGET
from documents.services.runtime_ollama import get_model_server_base_url, load_ollama_runtime
from documents.services.text_extract import (
    extract_text_from_pdf,
    ocr_image_bytes,
    pdf_first_page_as_png_bytes,
)
from documents.services.vendor_learning import profile_prompt_hints, update_vendor_profile_from_extracted
from documents.services.webhooks import emit_document_event

logger = logging.getLogger(__name__)

try:
    from crewai import Agent, Crew, LLM, Process, Task

    CREWAI_AVAILABLE = True
except Exception:
    CREWAI_AVAILABLE = False


def _extract_printed_summary_from_ocr(ocr_text: str) -> dict[str, Decimal | str]:
    """
    Deterministic parser for printed summary lines on long grocery receipts.
    Prioritizes bottom summary lines like BALANCE / TAX over noisy line-item OCR.
    """
    text = (ocr_text or "").strip()
    if not text:
        return {}
    out: dict[str, Decimal | str] = {}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    vendor_stopwords = {
        "GROCERY",
        "PRODUCE",
        "DELI",
        "MEAT",
        "BAKED GOODS",
        "LIQUOR",
        "MISCELLANEOUS",
        "CARD SAVINGS",
        "REGULAR PRICE",
        "QTY",
    }
    bad_vendor_tokens = {"TD", "TR", "TABLE", "COLSPAN", "REGULAR", "SAVINGS", "QTY"}
    for ln in lines[:12]:
        candidate = re.sub(r"[^A-Z&.\-\s]", "", ln.upper()).strip()
        words = [w for w in candidate.split() if w]
        if (
            len(candidate) >= 4
            and len(candidate) <= 40
            and len(words) <= 4
            and candidate not in vendor_stopwords
            and not any(tok in words for tok in bad_vendor_tokens)
        ):
            out["vendor_name"] = candidate.title()
            break

    money_pattern = re.compile(r"([0-9]+\.[0-9]{2})")
    for ln in lines:
        up = ln.upper()
        values = [Decimal(m.group(1)) for m in money_pattern.finditer(up)]
        if not values:
            continue
        last_amount = values[-1]
        if "BALANCE" in up or "AMOUNT DUE" in up:
            out["total_amount"] = last_amount
        elif "SUBTOTAL" in up and "total_amount" not in out:
            out["subtotal"] = last_amount
        elif re.search(r"\bTAX\b", up):
            # Exclude item names that contain TAX but still keep explicit tax summary lines.
            if "TAXABLE" not in up:
                out["tax_amount"] = last_amount

    return out


def _ocr_top_band(image_bytes: bytes, *, rt, base_vision: str) -> str:
    """
    Run OCR on the top area only, where vendor/date typically appear.
    """
    try:
        with Image.open(BytesIO(image_bytes)) as im:
            width, height = im.size
            if width < 20 or height < 20:
                return ""
            band = im.crop((0, 0, width, max(40, int(height * 0.22))))
            buf = BytesIO()
            band.save(buf, format="PNG")
            return ocr_image_bytes(
                buf.getvalue(),
                ollama_model=_resolved_ocr_model(rt),
                ollama_base_url=base_vision,
                vision_capable=rt.vision_model_supports_vision,
                skip_capability_gate=_ocr_skip_capability_gate(rt),
            )
    except Exception:
        return ""


def _run_crewai_hint(
    *,
    text_for_model: str,
    read_model_name: str,
    structure_model_name: str,
    validate_model_name: str,
    timeout_seconds: int,
    max_retries: int,
    hint_max_chars: int,
    base_url: str,
) -> str:
    """
    Get short extraction guidance from CrewAI agents.

    Safeguarded for reliability: fast timeout semantics at caller level and hard output trimming.
    """
    if not CREWAI_AVAILABLE or not text_for_model.strip():
        return ""
    try:
        read_llm = LLM(
            model=f"ollama/{read_model_name}",
            base_url=base_url.rstrip("/"),
            temperature=0,
        )
        structure_llm = LLM(
            model=f"ollama/{structure_model_name}",
            base_url=base_url.rstrip("/"),
            temperature=0,
        )
        validate_llm = LLM(
            model=f"ollama/{validate_model_name}",
            base_url=base_url.rstrip("/"),
            temperature=0,
        )
        read_agent = Agent(
            role="Receipt Reader",
            goal="Find high-confidence receipt fields from OCR text.",
            backstory="Expert in noisy OCR and receipt parsing.",
            llm=read_llm,
            allow_delegation=False,
            verbose=False,
        )
        structure_agent = Agent(
            role="Receipt Structurer",
            goal="Translate OCR analysis into strict extraction constraints.",
            backstory="Expert in field normalization and conservative extraction.",
            llm=structure_llm,
            allow_delegation=False,
            verbose=False,
        )
        validate_agent = Agent(
            role="Receipt Validator",
            goal="Produce concise anti-hallucination guidance for extraction.",
            backstory="Expert in totals and date normalization.",
            llm=validate_llm,
            allow_delegation=False,
            verbose=False,
        )
        t1 = Task(
            description=(
                "Read OCR text and identify strongest candidates for vendor, date, subtotal, tax, total. "
                "OCR text:\n"
                f"{text_for_model[:DEFAULT_EXTRACTION_TEXT_BUDGET]}"
            ),
            expected_output="Short bullet list of high-confidence fields.",
            agent=read_agent,
        )
        t2 = Task(
            description=(
                "Convert analysis into strict extraction constraints with emphasis on totals and date correctness."
            ),
            expected_output="Strict extraction constraints.",
            agent=structure_agent,
        )
        t3 = Task(
            description=(
                "From prior analysis, write 3-6 short extraction constraints to reduce hallucinations. "
                "Focus on subtotal/tax/total correctness and date normalization."
            ),
            expected_output="Concise extraction constraints.",
            agent=validate_agent,
        )
        attempts = max(1, int(max_retries) + 1)
        deadline = time.perf_counter() + max(5, int(timeout_seconds))
        last_error = None
        for _ in range(attempts):
            if time.perf_counter() > deadline:
                break
            try:
                crew = Crew(
                    agents=[read_agent, structure_agent, validate_agent],
                    tasks=[t1, t2, t3],
                    process=Process.sequential,
                    verbose=False,
                )
                out = crew.kickoff()
                hint = str(out or "").strip()
                return hint[: max(200, int(hint_max_chars))]
            except Exception as exc:
                last_error = exc
                continue
        if last_error:
            logger.warning("CrewAI hint retries exhausted: %s", last_error)
            return ""
        return ""
    except Exception:
        logger.exception("CrewAI hint generation failed")
        return ""


def run_crewai_pipeline(document_id: int) -> None:
    """
    CrewAI-orchestrated full pipeline:
    read -> structure -> validate -> category -> persist.
    """
    doc = InvoiceDocument.objects.select_related("uploaded_by").get(pk=document_id)
    path = Path(doc.file.path)
    suffix = _suffix(doc.original_filename or path.name)
    rt = load_ollama_runtime()
    base_text = get_model_server_base_url("text", rt)
    base_vision = get_model_server_base_url("vision", rt)

    append_extraction_log(
        document_id,
        "info",
        "Crew pipeline started.",
        event="crew_stage_start",
    )
    hints = build_correction_hints()
    model_used = rt.ollama_text_model
    crew_read_model = (getattr(rt, "crew_read_model", "") or rt.ollama_text_model).strip()
    crew_structure_model = (getattr(rt, "crew_structure_model", "") or rt.ollama_text_model).strip()
    crew_validate_model = (getattr(rt, "crew_validate_model", "") or rt.ollama_text_model).strip()
    crew_category_model = (getattr(rt, "crew_category_model", "") or rt.ollama_text_model).strip()
    crew_stage_timeout_seconds = int(getattr(rt, "crew_stage_timeout_seconds", 45))
    crew_max_retries = int(getattr(rt, "crew_max_retries", 2))
    crew_hint_max_chars = int(getattr(rt, "crew_hint_max_chars", 1200))
    max_rescan_attempts = int(getattr(rt, "max_document_rescan_attempts", 2))
    rescan_backoff_seconds = int(getattr(rt, "rescan_backoff_seconds", 0))

    append_extraction_log(
        document_id,
        "info",
        "Pipeline started.",
        event="extraction_started",
        details={
            "suffix": suffix,
            "text_base": base_text,
            "vision_base": base_vision,
            "text_model": rt.ollama_text_model,
            "ocr_model": _resolved_ocr_model(rt),
            "crewai_available": CREWAI_AVAILABLE,
            "crew_read_model": crew_read_model,
            "crew_structure_model": crew_structure_model,
            "crew_validate_model": crew_validate_model,
            "crew_category_model": crew_category_model,
            "crew_stage_timeout_seconds": crew_stage_timeout_seconds,
            "crew_max_retries": crew_max_retries,
            "crew_hint_max_chars": crew_hint_max_chars,
            "max_document_rescan_attempts": max_rescan_attempts,
            "rescan_backoff_seconds": rescan_backoff_seconds,
        },
    )

    try:
        total_attempts = max(1, max_rescan_attempts + 1)
        attempt_no = 1
        final_status = DocumentStatus.AUDIT_REQUIRED
        while attempt_no <= total_attempts:
            force_ocr_rescan = attempt_no > 1
            text_for_model = ""
            image_bytes: bytes | None = None

            append_extraction_log(
                document_id,
                "info",
                f"Rescan attempt {attempt_no}/{total_attempts} started.",
                event="rescan_attempt_started",
                details={"attempt": attempt_no, "total": total_attempts, "force_ocr_rescan": force_ocr_rescan},
            )
            InvoiceDocument.objects.filter(pk=document_id).update(
                extraction_attempts=attempt_no,
                last_rescan_reason="" if attempt_no == 1 else "deterministic_audit_failed",
            )

            append_extraction_log(document_id, "info", "Reading source document.", event="crew_stage_read")
            if suffix in PDF_EXT:
                append_extraction_log(document_id, "info", "Detected PDF.", event="pdf_detected")
                text_for_model = extract_text_from_pdf(path)
                append_extraction_log(
                    document_id,
                    "info",
                    f"PDF text layer length: {len(text_for_model)} chars.",
                    event="pdf_text_extracted",
                    details={"chars": len(text_for_model)},
                )
                if rt.use_vision_extraction or not text_for_model.strip() or force_ocr_rescan:
                    try:
                        image_bytes = pdf_first_page_as_png_bytes(path)
                        append_extraction_log(
                            document_id,
                            "info",
                            f"First-page rasterized ({len(image_bytes)} bytes).",
                            event="pdf_raster_ok",
                        )
                    except Exception as exc:
                        append_extraction_log(
                            document_id,
                            "warning",
                            f"PDF rasterize failed: {exc}",
                            event="pdf_raster_failed",
                        )
            elif suffix in IMAGE_EXT:
                append_extraction_log(document_id, "info", "Detected image receipt.", event="image_detected")
                image_bytes = path.read_bytes()
                if force_ocr_rescan or not (rt.use_vision_extraction and rt.vision_model_supports_vision):
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
                        f"Ollama OCR (rescan/text path): {len(text_for_model)} chars.",
                        event="image_ocr",
                    )
            else:
                append_extraction_log(
                    document_id,
                    "info",
                    f"Generic file suffix {suffix!r}; attempting OCR.",
                    event="generic_file",
                )
                image_bytes = path.read_bytes()
                text_for_model = ocr_image_bytes(
                    image_bytes,
                    ollama_model=_resolved_ocr_model(rt),
                    ollama_base_url=base_vision,
                    vision_capable=rt.vision_model_supports_vision,
                    skip_capability_gate=_ocr_skip_capability_gate(rt),
                )

            append_extraction_log(document_id, "info", "Structuring fields.", event="crew_stage_structure")
            parsed = None
            raw_response = ""
            errors: list[str] = []

            structured_vision_model = not _model_name_is_ocr_tuned(rt.ollama_vision_model or "")
            use_vision_path = (
                (not force_ocr_rescan)
                and rt.use_vision_extraction
                and rt.vision_model_supports_vision
                and image_bytes
                and structured_vision_model
            )
            if use_vision_path:
                append_extraction_log(
                    document_id,
                    "info",
                    f"Calling vision model {rt.ollama_vision_model!r}.",
                    event="ollama_vision_attempt",
                )
                try:
                    parsed, raw_response, errors = extract_with_retries(
                        _build_prompt_vision(hints),
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
                        details={"retry_errors": errors[:4], "raw_chars": len(raw_response or "")},
                    )
                except Exception as exc:
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
                    )
                if not text_for_model.strip():
                    raise RuntimeError("No usable OCR/text content found for extraction.")

                crew_hint = ""
                if getattr(rt, "use_crewai_hints", True):
                    crew_hint = _run_crewai_hint(
                        text_for_model=text_for_model,
                        read_model_name=crew_read_model,
                        structure_model_name=crew_structure_model,
                        validate_model_name=crew_validate_model,
                        timeout_seconds=crew_stage_timeout_seconds,
                        max_retries=crew_max_retries,
                        hint_max_chars=crew_hint_max_chars,
                        base_url=base_text,
                    )
                combined_hints = hints
                if crew_hint:
                    combined_hints = (combined_hints + "\n\nCrew guidance:\n" + crew_hint).strip()
                    append_extraction_log(
                        document_id,
                        "info",
                        "CrewAI guidance generated.",
                        event="crew_stage_guidance",
                    )
                prompt = _build_prompt_from_text(text_for_model, combined_hints)
                append_extraction_log(
                    document_id,
                    "info",
                    f"Calling text model {rt.ollama_text_model!r}.",
                    event="ollama_text_attempt",
                    details={"prompt_text_chars": min(len(text_for_model), DEFAULT_EXTRACTION_TEXT_BUDGET)},
                )
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
                    details={"retry_errors": errors[:5], "raw_chars": len(raw_response or "")},
                )

            _cleanup_line_items(parsed)
            vendor_hint = profile_prompt_hints(parsed.vendor_name or "")
            if vendor_hint:
                append_extraction_log(
                    document_id,
                    "info",
                    "Vendor profile guidance applied for future runs.",
                    event="vendor_profile_hint",
                )
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
            if not parsed.invoice_number and fallback_text.strip():
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
            if text_for_model.strip():
                summary = _extract_printed_summary_from_ocr(text_for_model)
                summary_updates: dict[str, str] = {}
                vendor = summary.get("vendor_name")
                if isinstance(vendor, str) and vendor and (not parsed.vendor_name or parsed.vendor_name.lower() in {"grocery", "store"}):
                    parsed.vendor_name = vendor
                    summary_updates["vendor_name"] = vendor

                parsed_total = summary.get("total_amount")
                if isinstance(parsed_total, Decimal):
                    if parsed.total_amount is None or abs(parsed.total_amount - parsed_total) > Decimal("0.05"):
                        parsed.total_amount = parsed_total
                        summary_updates["total_amount"] = str(parsed_total)
                parsed_tax = summary.get("tax_amount")
                if isinstance(parsed_tax, Decimal):
                    if parsed.tax_amount is None or abs(parsed.tax_amount - parsed_tax) > Decimal("0.05"):
                        parsed.tax_amount = parsed_tax
                        summary_updates["tax_amount"] = str(parsed_tax)
                parsed_subtotal = summary.get("subtotal")
                if isinstance(parsed_subtotal, Decimal):
                    if parsed.subtotal is None or abs(parsed.subtotal - parsed_subtotal) > Decimal("0.05"):
                        parsed.subtotal = parsed_subtotal
                        summary_updates["subtotal"] = str(parsed_subtotal)
                elif isinstance(parsed.total_amount, Decimal) and isinstance(parsed.tax_amount, Decimal):
                    recomputed = (parsed.total_amount - parsed.tax_amount).quantize(Decimal("0.01"))
                    if parsed.subtotal is None or abs(parsed.subtotal - recomputed) > Decimal("0.10"):
                        parsed.subtotal = recomputed
                        summary_updates["subtotal"] = str(recomputed)

                if summary_updates:
                    append_extraction_log(
                        document_id,
                        "info",
                        "Applied deterministic OCR summary corrections.",
                        event="ocr_summary_corrections",
                        details=summary_updates,
                    )
            if (parsed.vendor_name or "").strip().upper() in {"GROCERY", "PRODUCE", "DELI", "MEAT", "LIQUOR"}:
                parsed.vendor_name = ""
            if image_bytes and (not parsed.vendor_name or parsed.date_issued is None):
                top_text = _ocr_top_band(image_bytes, rt=rt, base_vision=base_vision)
                if top_text.strip():
                    append_extraction_log(
                        document_id,
                        "info",
                        "Ran top-band OCR fallback for header fields.",
                        event="ocr_top_band_fallback",
                    )
                    if not parsed.vendor_name:
                        top_summary = _extract_printed_summary_from_ocr(top_text)
                        fallback_vendor = top_summary.get("vendor_name")
                        if isinstance(fallback_vendor, str) and fallback_vendor:
                            parsed.vendor_name = fallback_vendor
                    if parsed.date_issued is None:
                        fallback_date = _infer_date_from_text(top_text)
                        if fallback_date is not None:
                            parsed.date_issued = fallback_date

            append_extraction_log(document_id, "info", "Validating and categorizing.", event="crew_stage_validate")
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
            audit = run_deterministic_audit(extracted)
            append_extraction_log(
                document_id,
                "info",
                f"Assigning category (crew category model configured: {crew_category_model}).",
                event="crew_stage_category",
            )
            cat, _reason = assign_category(extracted)
            extracted.category = cat
            extracted.save(update_fields=["category"])
            update_vendor_profile_from_extracted(extracted)

            has_cat = cat is not None
            conf = heuristic_confidence(audit, has_cat)
            final_status = DocumentStatus.VERIFIED if (audit["all_ok"] and has_cat) else DocumentStatus.AUDIT_REQUIRED
            doc.confidence_score = conf
            doc.status = final_status
            doc.extraction_error = "; ".join(audit["messages"]) if audit["messages"] else ""
            doc.extraction_attempts = attempt_no
            doc.last_rescan_reason = "" if final_status == DocumentStatus.VERIFIED else "deterministic_audit_failed"
            doc.save(
                update_fields=[
                    "confidence_score",
                    "status",
                    "extraction_error",
                    "extraction_attempts",
                    "last_rescan_reason",
                ]
            )

            append_extraction_log(
                document_id,
                "warning" if final_status == DocumentStatus.AUDIT_REQUIRED else "info",
                f"Deterministic audit all_ok={audit['all_ok']}; category={getattr(cat, 'name', None)}; status={final_status}.",
                event="audit_complete",
                details={
                    "all_ok": audit["all_ok"],
                    "messages": audit["messages"][:12],
                    "confidence": float(conf),
                    "category": getattr(cat, "name", None),
                    "document_status": final_status,
                    "attempt": attempt_no,
                },
            )
            append_extraction_log(
                document_id,
                "info",
                f"Rescan attempt {attempt_no}/{total_attempts} finished.",
                event="rescan_attempt_finished",
                details={"attempt": attempt_no, "status": final_status},
            )

            if final_status == DocumentStatus.VERIFIED:
                break
            if attempt_no >= total_attempts:
                append_extraction_log(
                    document_id,
                    "warning",
                    "Maximum rescan attempts reached; leaving document in audit_required.",
                    event="rescan_max_reached",
                    details={"attempts": attempt_no},
                )
                break

            if rescan_backoff_seconds > 0:
                append_extraction_log(
                    document_id,
                    "info",
                    f"Waiting {rescan_backoff_seconds}s before next rescan attempt.",
                    event="rescan_backoff",
                )
                time.sleep(rescan_backoff_seconds)
            attempt_no += 1

        append_extraction_log(document_id, "info", "Crew pipeline finished.", event="crew_stage_finish")
        append_extraction_log(document_id, "info", "Pipeline finished successfully.", event="extraction_finished")

    except Exception as exc:
        logger.exception("Crew pipeline failed for document %s", document_id)
        append_extraction_log(document_id, "error", str(exc), event="crew_stage_failed")
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
        fail_doc = InvoiceDocument.objects.filter(pk=document_id).first()
        if fail_doc:
            emit_document_event("document.failed", fail_doc, {"error": str(exc)[:500]})
