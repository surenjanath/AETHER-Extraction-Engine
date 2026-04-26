from __future__ import annotations

from documents.models import ExtractedData, InvoiceDocument
from documents.services.runtime_ollama import load_ollama_runtime


def detect_duplicate_on_upload(document: InvoiceDocument) -> None:
    """Exact duplicate detection using file hash."""
    settings = load_ollama_runtime()
    if not settings.enable_duplicate_detection or not document.file_sha256:
        return
    same_hash = (
        InvoiceDocument.objects.filter(
            uploaded_by=document.uploaded_by,
            file_sha256=document.file_sha256,
        )
        .exclude(pk=document.pk)
        .order_by("upload_date")
        .first()
    )
    if same_hash:
        document.is_duplicate = True
        document.duplicate_confidence = 1.0
        document.canonical_document = same_hash.canonical_document or same_hash
        document.duplicate_group = same_hash.duplicate_group or document.file_sha256[:20]
        document.duplicate_reason = "sha256_exact_match"


def fuzzy_duplicate_scan(document: InvoiceDocument) -> None:
    """Best-effort duplicate detection from vendor/date/total signals."""
    settings = load_ollama_runtime()
    if not settings.enable_duplicate_detection:
        return
    extracted = getattr(document, "extracted", None)
    if not extracted:
        return
    candidates = (
        ExtractedData.objects.filter(
            document__uploaded_by=document.uploaded_by,
            document__status__in=["verified", "audit_required"],
        )
        .exclude(document_id=document.pk)
        .select_related("document")
        .order_by("-document__upload_date")[:120]
    )
    best_doc = None
    best_score = 0.0
    for cand in candidates:
        score = _fuzzy_score(extracted, cand)
        if score > best_score:
            best_score = score
            best_doc = cand.document
    if best_doc and best_score >= 0.92:
        document.is_duplicate = True
        document.duplicate_confidence = round(best_score, 3)
        document.canonical_document = best_doc.canonical_document or best_doc
        document.duplicate_group = best_doc.duplicate_group or f"fuzzy-{best_doc.pk}"
        document.duplicate_reason = "fuzzy_vendor_date_total"


def merge_duplicate_into_canonical(duplicate: InvoiceDocument, canonical: InvoiceDocument) -> None:
    duplicate.is_duplicate = True
    duplicate.canonical_document = canonical
    duplicate.duplicate_group = canonical.duplicate_group or f"group-{canonical.pk}"
    duplicate.duplicate_reason = "manual_merge"
    duplicate.save(
        update_fields=[
            "is_duplicate",
            "canonical_document",
            "duplicate_group",
            "duplicate_reason",
        ]
    )


def _fuzzy_score(a: ExtractedData, b: ExtractedData) -> float:
    score = 0.0
    if (a.vendor_name or "").strip().lower() and (a.vendor_name or "").strip().lower() == (
        (b.vendor_name or "").strip().lower()
    ):
        score += 0.45
    if a.total_amount is not None and b.total_amount is not None and abs(a.total_amount - b.total_amount) <= 0.01:
        score += 0.4
    if a.date_issued and b.date_issued:
        delta_days = abs((a.date_issued - b.date_issued).days)
        if delta_days == 0:
            score += 0.15
        elif delta_days <= 1:
            score += 0.08
    return score

