"""Synchronous document processing tasks."""

from __future__ import annotations

import logging
import threading
import zipfile
from pathlib import Path

from django.db import close_old_connections
from django.core.files.base import ContentFile
from django.utils import timezone

from documents.models import InvoiceDocument
from documents.services.duplicate_detection import fuzzy_duplicate_scan
from documents.services.extraction_logging import append_extraction_log
from documents.services.webhooks import emit_document_event

logger = logging.getLogger(__name__)

SAFE_SUFFIX = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _run_background(target, *args) -> None:
    """Run task in a detached thread (single-process fallback, no external worker)."""

    def runner():
        close_old_connections()
        try:
            target(*args)
        except Exception:
            logger.exception("Background task failed: %s args=%s", target.__name__, args)
        finally:
            close_old_connections()

    t = threading.Thread(target=runner, name=f"task-{target.__name__}", daemon=True)
    t.start()


def enqueue_extract_invoice_document(document_id: int) -> None:
    _run_background(extract_invoice_document, document_id)


def enqueue_process_zip_archive(document_id: int) -> None:
    _run_background(process_zip_archive, document_id)


def extract_invoice_document(document_id: int) -> None:
    from documents.services.crew_pipeline import run_crewai_pipeline

    now = timezone.now()
    InvoiceDocument.objects.filter(pk=document_id, first_processing_started_at__isnull=True).update(
        first_processing_started_at=now
    )
    InvoiceDocument.objects.filter(pk=document_id).update(last_processing_started_at=now)
    append_extraction_log(
        document_id,
        "info",
        "Started extraction task (CrewAI pipeline).",
        event="task_started",
    )
    run_crewai_pipeline(document_id)
    doc = InvoiceDocument.objects.filter(pk=document_id).first()
    if not doc:
        return
    doc.last_processing_finished_at = timezone.now()
    doc.save(update_fields=["last_processing_finished_at"])
    try:
        fuzzy_duplicate_scan(doc)
        if doc.is_duplicate:
            doc.save(
                update_fields=[
                    "is_duplicate",
                    "duplicate_confidence",
                    "canonical_document",
                    "duplicate_group",
                    "duplicate_reason",
                ]
            )
            emit_document_event("document.duplicate_detected", doc)
        if doc.status == "verified":
            if not doc.verified_at:
                doc.verified_at = timezone.now()
                doc.save(update_fields=["verified_at"])
            emit_document_event("document.verified", doc)
        elif doc.status == "audit_required":
            emit_document_event("document.audit_required", doc)
    except Exception:
        logger.exception("Post-extraction hooks failed for document %s", document_id)


def process_zip_archive(document_id: int) -> None:
    """
    Unpack a ZIP `InvoiceDocument` into child documents and enqueue extraction.
    Removes the ZIP row afterward.
    """
    parent = InvoiceDocument.objects.select_related("uploaded_by").get(pk=document_id)
    path = Path(parent.file.path)
    user = parent.uploaded_by

    if path.suffix.lower() != ".zip":
        logger.warning("process_zip_archive called on non-zip %s", path)
        return

    logger.info(
        "ZIP unpack started document_id=%s file=%s", document_id, parent.original_filename
    )
    created_ids: list[int] = []
    with zipfile.ZipFile(path, "r") as zf:
        for name in zf.namelist():
            if name.endswith("/") or name.startswith("__MACOSX"):
                continue
            member = Path(name)
            suf = member.suffix.lower()
            if suf not in SAFE_SUFFIX:
                continue
            data = zf.read(name)
            if not data:
                continue
            child = InvoiceDocument(
                uploaded_by=user,
                original_filename=member.name,
            )
            child.file.save(member.name, ContentFile(data), save=True)
            created_ids.append(child.pk)
            append_extraction_log(
                child.pk,
                "info",
                f"Unpacked from ZIP upload (original archive id was {document_id}).",
                event="zip_member_created",
                details={
                    "member": member.name,
                    "zip_filename": parent.original_filename,
                    "bytes": len(data),
                },
            )
            extract_invoice_document(child.pk)

    parent.file.delete(save=False)
    parent.delete()

    for cid in created_ids:
        logger.info("ZIP extracted child document %s from zip %s", cid, document_id)
