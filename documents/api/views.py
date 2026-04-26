from __future__ import annotations

import csv
from datetime import date
from io import BytesIO
from typing import Optional

from django.contrib.auth.models import AbstractUser
from django.db.models import Count
from django.http import HttpResponse
from django.utils.dateparse import parse_date
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from documents.models import (
    ApiKey,
    DocumentStatus,
    ExtractedData,
    ExtractionLog,
    InvoiceDocument,
    SystemSettings,
    WebhookEndpoint,
)
from documents.services.duplicate_detection import merge_duplicate_into_canonical
from documents.services.ollama_health import check_ollama_tags
from documents.services.ollama_model_ops import (
    infer_capabilities,
    ollama_pull_sync,
    ollama_show,
    ollama_tags_full,
    refresh_capabilities_after_save,
)
from documents.services.runtime_ollama import get_model_server_base_url, load_ollama_runtime
from documents.tasks import (
    enqueue_extract_invoice_document,
    enqueue_process_zip_archive,
)
from documents.services.webhooks import emit_document_event
from .serializers import (
    InvoiceDocumentCreateSerializer,
    InvoiceDocumentSerializer,
)


def async_task(task_name: str, *args):
    """Compatibility shim used by tests and legacy call sites."""
    if task_name == "documents.tasks.extract_invoice_document":
        enqueue_extract_invoice_document(*args)
    elif task_name == "documents.tasks.process_zip_archive":
        enqueue_process_zip_archive(*args)


class InvoiceDocumentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "post", "head", "options"]

    def get_serializer_class(self):
        if self.action == "create":
            return InvoiceDocumentCreateSerializer
        return InvoiceDocumentSerializer

    def get_queryset(self):
        return (
            InvoiceDocument.objects.filter(uploaded_by=self.request.user)
            .select_related("extracted__category")
            .prefetch_related("extracted__line_items")
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        output = InvoiceDocumentSerializer(
            serializer.instance,
            context={"request": request},
        )
        return Response(output.data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        doc = serializer.save()
        name = (doc.original_filename or doc.file.name or "").lower()
        if name.endswith(".zip"):
            async_task("documents.tasks.process_zip_archive", doc.pk)
        else:
            async_task("documents.tasks.extract_invoice_document", doc.pk)

    @action(detail=True, methods=["post"], url_path="requeue")
    def requeue(self, request, pk=None):
        """Re-enqueue background extraction for pending or audit-required documents."""
        doc = self.get_object()
        if doc.status not in (
            DocumentStatus.PENDING_EXTRACTION,
            DocumentStatus.AUDIT_REQUIRED,
        ):
            return Response(
                {
                    "detail": "Requeue is only allowed when status is pending_extraction or audit_required.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        async_task("documents.tasks.extract_invoice_document", doc.pk)
        return Response({"detail": "queued", "id": doc.pk}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="live")
    def live(self, request, pk=None):
        """Live extraction snapshot for UI polling."""
        doc = self.get_object()
        extracted = getattr(doc, "extracted", None)
        recent_logs = list(
            ExtractionLog.objects.filter(document_id=doc.pk)
            .order_by("-created_at")
            .values("created_at", "level", "event", "message")[:12]
        )
        recent_logs.reverse()
        return Response(
            {
                "id": doc.pk,
                "status": doc.status,
                "extraction_error": doc.extraction_error or "",
                "extraction_attempts": doc.extraction_attempts,
                "last_rescan_reason": doc.last_rescan_reason or "",
                "extracted": (
                    {
                        "vendor_name": extracted.vendor_name or "",
                        "date_issued": extracted.date_issued.isoformat()
                        if extracted and extracted.date_issued
                        else "",
                        "invoice_number": extracted.invoice_number or ""
                        if extracted
                        else "",
                        "document_type": extracted.document_type or "unknown"
                        if extracted
                        else "unknown",
                        "subtotal": str(extracted.subtotal or "")
                        if extracted
                        else "",
                        "tax_amount": str(extracted.tax_amount or "")
                        if extracted
                        else "",
                        "total_amount": str(extracted.total_amount or "")
                        if extracted
                        else "",
                    }
                    if extracted
                    else None
                ),
                "recent_logs": recent_logs,
            }
        )

    @action(detail=True, methods=["post"], url_path="mark-duplicate")
    def mark_duplicate(self, request, pk=None):
        doc = self.get_object()
        canonical_id = request.data.get("canonical_id")
        canonical = None
        if canonical_id and str(canonical_id).isdigit():
            canonical = (
                InvoiceDocument.objects.filter(uploaded_by=request.user, pk=int(canonical_id))
                .exclude(pk=doc.pk)
                .first()
            )
        if not canonical:
            canonical = (
                InvoiceDocument.objects.filter(uploaded_by=request.user, is_duplicate=False)
                .exclude(pk=doc.pk)
                .order_by("-upload_date")
                .first()
            )
        if not canonical:
            return Response({"detail": "No canonical document found."}, status=status.HTTP_400_BAD_REQUEST)
        merge_duplicate_into_canonical(doc, canonical)
        emit_document_event("document.duplicate_detected", doc, {"source": "api"})
        return Response({"detail": "marked_duplicate", "canonical_id": canonical.pk})

    @action(detail=True, methods=["post"], url_path="ignore-duplicate")
    def ignore_duplicate(self, request, pk=None):
        doc = self.get_object()
        doc.is_duplicate = False
        doc.canonical_document = None
        doc.duplicate_confidence = None
        doc.duplicate_reason = "manual_ignore_duplicate"
        doc.save(
            update_fields=[
                "is_duplicate",
                "canonical_document",
                "duplicate_confidence",
                "duplicate_reason",
            ]
        )
        return Response({"detail": "duplicate_cleared"})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def queue_stats(request):
    qs = (
        InvoiceDocument.objects.filter(uploaded_by=request.user)
        .values("status")
        .annotate(c=Count("id"))
    )
    counts = {row["status"]: row["c"] for row in qs}
    return Response(
        {
            "pending_extraction": counts.get(DocumentStatus.PENDING_EXTRACTION, 0),
            "audit_required": counts.get(DocumentStatus.AUDIT_REQUIRED, 0),
            "verified": counts.get(DocumentStatus.VERIFIED, 0),
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def health_ollama(request):
    """Reachability check for Ollama (`/api/tags`)."""
    text_payload = check_ollama_tags(role="text")
    vision_payload = check_ollama_tags(role="vision")
    ok = bool(text_payload.get("ok")) and bool(vision_payload.get("ok"))
    return Response(
        {
            "ok": ok,
            "text": text_payload,
            "vision": vision_payload,
            "checked_at": text_payload.get("checked_at") or vision_payload.get("checked_at"),
            "models_sample": text_payload.get("models_sample", []),
            "error": None if ok else f"text={text_payload.get('error')}; vision={vision_payload.get('error')}",
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def ollama_tags_list(request):
    """List models from Ollama `/api/tags` (optional `?base_url=`)."""
    raw = (request.query_params.get("base_url") or "").strip()
    role = (request.query_params.get("role") or "text").strip().lower()
    base = (
        raw.rstrip("/")
        if raw
        else get_model_server_base_url(role, load_ollama_runtime())
    )
    if not base:
        return Response(
            {"models": [], "detail": "base URL is empty"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        models = ollama_tags_full(base)
    except Exception as exc:
        return Response({"models": [], "detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    return Response({"models": models})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ollama_prepare_model(request):
    """
    Inspect/pull model via Ollama; update stored model name and capability flags.
    """
    role = request.data.get("role")
    name = (request.data.get("name") or "").strip()
    do_pull = request.data.get("pull", True)
    if isinstance(do_pull, str):
        do_pull = do_pull.lower() in ("1", "true", "yes")

    if role not in ("vision", "text"):
        return Response(
            {"detail": "role must be vision or text", "ok": False},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not name:
        return Response(
            {"detail": "name is required", "ok": False},
            status=status.HTTP_400_BAD_REQUEST,
        )

    s = load_ollama_runtime()
    base_in = (request.data.get("base_url") or "").strip()
    base = base_in.rstrip("/") if base_in else get_model_server_base_url(role, s)
    if not base:
        return Response(
            {"detail": "Configure model-server base URL in settings first", "ok": False},
            status=status.HTTP_400_BAD_REQUEST,
        )

    pull_status = "skipped"
    if do_pull:
        ok_pull, msg = ollama_pull_sync(base, name)
        pull_status = msg
        if not ok_pull:
            return Response(
                {"detail": msg, "ok": False},
                status=status.HTTP_400_BAD_REQUEST,
            )

    try:
        show = ollama_show(base, name)
    except Exception as exc:
        return Response(
            {"detail": str(exc), "ok": False},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    has_vis, has_tools, caps = infer_capabilities(show, name)

    if role == "vision":
        SystemSettings.objects.filter(pk=s.pk).update(ollama_vision_model=name)
    else:
        SystemSettings.objects.filter(pk=s.pk).update(ollama_text_model=name)

    refresh_capabilities_after_save(load_ollama_runtime())
    s3 = load_ollama_runtime()

    return Response(
        {
            "ok": True,
            "role": role,
            "model": name,
            "capabilities": caps,
            "has_vision": has_vis,
            "has_tools": has_tools,
            "pull_status": pull_status,
            "vision_model_supports_vision": s3.vision_model_supports_vision,
            "text_model_supports_tools": s3.text_model_supports_tools,
        }
    )


def _verified_extracted_qs(
    user: AbstractUser,
    date_from: Optional[date],
    date_to: Optional[date],
):
    qs = (
        ExtractedData.objects.filter(
            document__uploaded_by=user,
            document__status=DocumentStatus.VERIFIED,
        )
        .select_related("document", "category")
        .order_by("date_issued", "id")
    )
    if date_from:
        qs = qs.filter(date_issued__gte=date_from)
    if date_to:
        qs = qs.filter(date_issued__lte=date_to)
    return qs


def stream_verified_csv(
    user: AbstractUser,
    date_from: Optional[date],
    date_to: Optional[date],
) -> HttpResponse:
    qs = _verified_extracted_qs(user, date_from, date_to)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="verified_export.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "document_id",
            "filename",
            "vendor",
            "date_issued",
            "subtotal",
            "tax",
            "total",
            "category",
        ]
    )
    for row in qs:
        writer.writerow(
            [
                row.document_id,
                row.document.original_filename,
                row.vendor_name,
                row.date_issued.isoformat() if row.date_issued else "",
                str(row.subtotal or ""),
                str(row.tax_amount or ""),
                str(row.total_amount or ""),
                row.category.name if row.category else "",
            ]
        )
    return response


def stream_verified_xlsx(
    user: AbstractUser,
    date_from: Optional[date],
    date_to: Optional[date],
) -> HttpResponse:
    from openpyxl import Workbook

    qs = _verified_extracted_qs(user, date_from, date_to)
    wb = Workbook()
    ws = wb.active
    ws.title = "verified"
    headers = [
        "document_id",
        "filename",
        "vendor",
        "date_issued",
        "subtotal",
        "tax",
        "total",
        "category",
    ]
    ws.append(headers)
    for row in qs:
        ws.append(
            [
                row.document_id,
                row.document.original_filename,
                row.vendor_name,
                row.date_issued.isoformat() if row.date_issued else "",
                float(row.subtotal) if row.subtotal is not None else None,
                float(row.tax_amount) if row.tax_amount is not None else None,
                float(row.total_amount) if row.total_amount is not None else None,
                row.category.name if row.category else "",
            ]
        )
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    response = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="verified_export.xlsx"'
    return response


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def export_csv(request):
    raw_df = request.query_params.get("from")
    raw_dt = request.query_params.get("to")
    df = parse_date(raw_df) if raw_df else None
    dt = parse_date(raw_dt) if raw_dt else None
    return stream_verified_csv(request.user, df, dt)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def export_xlsx(request):
    raw_df = request.query_params.get("from")
    raw_dt = request.query_params.get("to")
    df = parse_date(raw_df) if raw_df else None
    dt = parse_date(raw_dt) if raw_dt else None
    return stream_verified_xlsx(request.user, df, dt)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_keys_list(request):
    if not request.user.is_superuser:
        return Response({"detail": "admin_only"}, status=status.HTTP_403_FORBIDDEN)
    rows = list(
        ApiKey.objects.select_related("created_by")
        .order_by("-created_at")
        .values("id", "name", "key_prefix", "is_active", "created_at", "last_used_at", "revoked_at")
    )
    return Response({"results": rows})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def webhook_test_send(request):
    if not request.user.is_superuser:
        return Response({"detail": "admin_only"}, status=status.HTTP_403_FORBIDDEN)
    endpoint_id = request.data.get("endpoint_id")
    if not endpoint_id or not str(endpoint_id).isdigit():
        return Response({"detail": "endpoint_id required"}, status=status.HTTP_400_BAD_REQUEST)
    endpoint = WebhookEndpoint.objects.filter(pk=int(endpoint_id)).first()
    if not endpoint:
        return Response({"detail": "endpoint_not_found"}, status=status.HTTP_404_NOT_FOUND)
    doc = (
        InvoiceDocument.objects.filter(uploaded_by=request.user)
        .order_by("-upload_date")
        .first()
    )
    if not doc:
        return Response({"detail": "no_documents"}, status=status.HTTP_400_BAD_REQUEST)
    emit_document_event("document.verified", doc, {"source": "test_send"})
    return Response({"detail": "test_event_dispatched"})
