from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import secrets
from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import Count, Q, F, Value, FloatField, ExpressionWrapper
from django.db.models.functions import Coalesce
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView

from documents.forms import (
    BatchAuditActionForm,
    CategoryForm,
    DateRangeForm,
    ExportForm,
    ExtractedDataForm,
    HistoryFilterForm,
    LineItemFormSet,
    SystemSettingsForm,
    WebhookEndpointForm,
)
from documents.models import (
    AIRuntimeLog,
    ApiKey,
    AuditLog,
    Category,
    DocumentStatus,
    ExportPreset,
    ExtractedData,
    ExtractionLog,
    InvoiceDocument,
    WebhookEndpoint,
)
from documents.services.audit import MONEY_EPS, run_deterministic_audit
from documents.services.duplicate_detection import merge_duplicate_into_canonical
from documents.services.ollama_health import check_ollama_tags
from documents.services.ollama_model_ops import refresh_capabilities_after_save
from documents.services.vendor_learning import learn_from_audit_logs
from documents.services.webhooks import emit_document_event
from documents.services.runtime_ollama import load_ollama_runtime
from documents.services.reporting import (
    audit_kpis,
    sla_metrics,
    spend_trend,
    verified_category_breakdown,
)


class AppLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True


class AppLogoutView(LogoutView):
    next_page = reverse_lazy("login")


class BulkUploadView(LoginRequiredMixin, TemplateView):
    template_name = "documents/bulk_upload.html"


class CategoriesView(LoginRequiredMixin, FormView):
    template_name = "documents/categories.html"
    form_class = CategoryForm
    success_url = reverse_lazy("documents:categories")

    def post(self, request, *args, **kwargs):
        if request.POST.get("approve_category"):
            return self._approve_system_category(request)
        if request.POST.get("rename_category"):
            return self._rename_category(request)
        return super().post(request, *args, **kwargs)

    def _approve_system_category(self, request):
        pk = int(request.POST["approve_category"])
        cat = get_object_or_404(Category, pk=pk)
        if not cat.is_system_generated:
            messages.info(request, "Category is already custom.")
        else:
            cat.is_system_generated = False
            cat.save(update_fields=["is_system_generated"])
            messages.success(request, f"Approved “{cat.name}” as a custom category.")
        return redirect("documents:categories")

    def _rename_category(self, request):
        pk = int(request.POST["rename_category"])
        new_name = (request.POST.get("rename_to") or "").strip()
        cat = get_object_or_404(Category, pk=pk)
        if not new_name:
            messages.error(request, "Name is required.")
            return redirect("documents:categories")
        if Category.objects.filter(name__iexact=new_name).exclude(pk=cat.pk).exists():
            messages.error(request, "Another category already uses that name.")
            return redirect("documents:categories")
        old = cat.name
        cat.name = new_name
        cat.save(update_fields=["name"])
        messages.success(request, f"Renamed “{old}” to “{new_name}”.")
        return redirect("documents:categories")

    def form_valid(self, form):
        obj = form.save(commit=False)
        obj.is_system_generated = False
        obj.save()
        messages.success(self.request, "Category added.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = Category.objects.all().order_by("name")
        return ctx


class HistoryView(LoginRequiredMixin, ListView):
    model = InvoiceDocument
    template_name = "documents/history.html"
    context_object_name = "documents"
    paginate_by = 25

    def get_queryset(self):
        user = self.request.user
        qs = (
            InvoiceDocument.objects.filter(uploaded_by=user)
            .select_related("extracted__category")
            .order_by("-upload_date")
        )
        form = HistoryFilterForm(self.request.GET or None)
        if not form.is_valid():
            return qs
        data = form.cleaned_data
        if q := (data.get("q") or "").strip():
            lk = Q(original_filename__icontains=q) | Q(extracted__vendor_name__icontains=q)
            if q.isdigit():
                lk |= Q(pk=int(q))
            qs = qs.filter(lk).distinct()
        if st := data.get("status"):
            qs = qs.filter(status=st)
        if cat := data.get("category"):
            qs = qs.filter(extracted__category=cat)
        if days := data.get("days"):
            try:
                nd = int(days)
            except (TypeError, ValueError):
                nd = 0
            if nd > 0:
                since = timezone.now() - timedelta(days=nd)
                qs = qs.filter(upload_date__gte=since)
        if data.get("only_duplicates"):
            qs = qs.filter(is_duplicate=True)
        return qs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = HistoryFilterForm(self.request.GET or None)
        user = self.request.user
        total = InvoiceDocument.objects.filter(uploaded_by=user).count()
        verified = InvoiceDocument.objects.filter(
            uploaded_by=user, status=DocumentStatus.VERIFIED
        ).count()
        denom = total - InvoiceDocument.objects.filter(
            uploaded_by=user, status=DocumentStatus.PENDING_EXTRACTION
        ).count()
        accuracy = round(100.0 * verified / denom, 1) if denom else 0.0
        ctx["history_total"] = total
        ctx["history_accuracy"] = accuracy
        return ctx


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "documents/dashboard.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        qs = (
            InvoiceDocument.objects.filter(uploaded_by=user)
            .values("status")
            .annotate(c=Count("id"))
        )
        counts = {row["status"]: row["c"] for row in qs}
        ctx["count_pending"] = counts.get(DocumentStatus.PENDING_EXTRACTION, 0)
        ctx["count_audit"] = counts.get(DocumentStatus.AUDIT_REQUIRED, 0)
        ctx["count_verified"] = counts.get(DocumentStatus.VERIFIED, 0)
        ctx["count_duplicates"] = InvoiceDocument.objects.filter(uploaded_by=user, is_duplicate=True).count()

        today = timezone.localdate()
        ctx["processed_today"] = InvoiceDocument.objects.filter(
            uploaded_by=user, upload_date__date=today
        ).count()

        # Math-related extraction issues (align with audit_math / deterministic audit wording).
        ctx["math_errors"] = (
            InvoiceDocument.objects.filter(uploaded_by=user)
            .filter(
                Q(extraction_error__icontains="Subtotal")
                | Q(extraction_error__icontains="mismatch")
                | Q(extraction_error__icontains="Line items sum")
                | Q(extraction_error__icontains="tolerance")
            )
            .count()
        )

        ctx["recent_documents"] = list(
            InvoiceDocument.objects.filter(uploaded_by=user)
            .select_related("extracted", "extracted__category")
            .order_by("-upload_date")[:10]
        )
        ctx["spend_trend"] = spend_trend(user, days=30)
        ctx["audit_kpis"] = audit_kpis(user)
        ctx["sla_metrics"] = sla_metrics(user)

        err = (
            InvoiceDocument.objects.filter(uploaded_by=user)
            .exclude(extraction_error="")
            .values("extraction_error")
            .annotate(n=Count("id"))
            .order_by("-n")
            .first()
        )
        if err and err["extraction_error"]:
            msg = err["extraction_error"].strip()
            ctx["insight_message"] = msg[:400] + ("…" if len(msg) > 400 else "")
        else:
            ctx["insight_message"] = None

        ctx["category_bars"] = verified_category_breakdown(user)[:6]
        ctx["ollama_health"] = check_ollama_tags()
        recent_logs = list(
            ExtractionLog.objects.filter(document__uploaded_by=user)
            .select_related("document")
            .order_by("-created_at")[:40]
        )
        ctx["recent_pipeline_logs"] = recent_logs[:8]
        ctx["critical_pipeline_logs"] = [
            log for log in recent_logs if log.level in ("warning", "error")
        ][:8]
        return ctx


class ExtractionLogListView(LoginRequiredMixin, ListView):
    """Latest extraction pipeline events (optionally filtered to one document)."""

    model = ExtractionLog
    template_name = "documents/extraction_logs.html"
    context_object_name = "logs"
    paginate_by = 40

    def get_queryset(self):
        qs = (
            ExtractionLog.objects.filter(document__uploaded_by=self.request.user)
            .select_related("document")
            .order_by("-created_at")
        )
        raw = self.request.GET.get("document")
        if raw and str(raw).isdigit():
            qs = qs.filter(document_id=int(raw))
        return qs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        raw = (self.request.GET.get("document") or "").strip()
        ctx["filter_document_id"] = raw
        ctx["filter_document_pk"] = int(raw) if raw.isdigit() else None
        return ctx


class AIRuntimeLogView(LoginRequiredMixin, ListView):
    """Global AI runtime logs (text + vision/ocr)."""

    model = AIRuntimeLog
    template_name = "documents/ai_runtime_logs.html"
    context_object_name = "logs"
    paginate_by = 50

    def get_queryset(self):
        qs = AIRuntimeLog.objects.all().order_by("-created_at")
        role = (self.request.GET.get("role") or "").strip().lower()
        if role in ("text", "vision", "ocr"):
            qs = qs.filter(role=role)
        level = (self.request.GET.get("level") or "").strip().lower()
        if level in ("info", "warning", "error"):
            qs = qs.filter(level=level)
        return qs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["filter_role"] = (self.request.GET.get("role") or "").strip().lower()
        ctx["filter_level"] = (self.request.GET.get("level") or "").strip().lower()
        return ctx


class AuditQueueView(LoginRequiredMixin, ListView):
    model = InvoiceDocument
    template_name = "documents/audit_queue.html"
    context_object_name = "documents"
    paginate_by = 25

    def get_queryset(self):
        return audit_queue_queryset(self.request.user)


def audit_queue_queryset(user):
    return (
        InvoiceDocument.objects.filter(
            uploaded_by=user,
            status=DocumentStatus.AUDIT_REQUIRED,
        )
        .select_related("extracted__category")
        .annotate(
            priority_score=ExpressionWrapper(
                (Value(1.0) - Coalesce(F("confidence_score"), Value(0.0)))
                + (Coalesce(F("extracted__total_amount"), Value(0.0), output_field=FloatField()) / Value(1000.0)),
                output_field=FloatField(),
            )
        )
        .order_by("-priority_score", "-upload_date")
    )


class BulkVerifyAuditView(LoginRequiredMixin, View):
    """POST: mark selected audit-required documents verified only when deterministic audit passes."""

    def post(self, request, *args, **kwargs):
        ids_raw = request.POST.getlist("doc_id")
        try:
            ids = [int(x) for x in ids_raw]
        except ValueError:
            messages.error(request, "Invalid document selection.")
            return redirect("documents:audit_queue")
        if not ids:
            messages.info(request, "No documents selected.")
            return redirect("documents:audit_queue")

        qs = (
            InvoiceDocument.objects.filter(
                uploaded_by=request.user,
                pk__in=ids,
                status=DocumentStatus.AUDIT_REQUIRED,
            )
            .select_related("extracted")
            .prefetch_related("extracted__line_items")
        )
        ok_count = 0
        skip_count = 0
        for doc in qs:
            extracted = getattr(doc, "extracted", None)
            if extracted is None:
                skip_count += 1
                continue
            audit = run_deterministic_audit(extracted)
            if audit["all_ok"]:
                doc.status = DocumentStatus.VERIFIED
                if not doc.verified_at:
                    doc.verified_at = timezone.now()
                doc.save(update_fields=["status", "verified_at"])
                emit_document_event("document.verified", doc, {"source": "bulk_verify"})
                ok_count += 1
            else:
                skip_count += 1

        if ok_count:
            messages.success(
                request,
                f"Marked {ok_count} document(s) verified (math checks passed).",
            )
        if skip_count:
            messages.warning(
                request,
                f"{skip_count} document(s) skipped (missing data or audit still failing).",
            )
        return redirect("documents:audit_queue")


class BulkAuditActionView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        form = BatchAuditActionForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Invalid bulk action payload.")
            return redirect("documents:audit_queue")
        ids = form.cleaned_data["doc_ids"]
        action = form.cleaned_data["action"]
        category = form.cleaned_data.get("category")
        docs = (
            InvoiceDocument.objects.filter(uploaded_by=request.user, pk__in=ids)
            .select_related("extracted")
            .prefetch_related("extracted__line_items")
        )
        changed = 0
        for doc in docs:
            if action == BatchAuditActionForm.ACTION_VERIFY:
                extracted = getattr(doc, "extracted", None)
                if extracted and run_deterministic_audit(extracted)["all_ok"]:
                    doc.status = DocumentStatus.VERIFIED
                    if not doc.verified_at:
                        doc.verified_at = timezone.now()
                    doc.save(update_fields=["status", "verified_at"])
                    emit_document_event("document.verified", doc, {"source": "bulk_action"})
                    changed += 1
            elif action == BatchAuditActionForm.ACTION_REQUEUE:
                if doc.status in (DocumentStatus.AUDIT_REQUIRED, DocumentStatus.PENDING_EXTRACTION):
                    from documents.tasks import enqueue_extract_invoice_document

                    enqueue_extract_invoice_document(doc.pk)
                    changed += 1
            elif action == BatchAuditActionForm.ACTION_MARK_DUP:
                canonical = (
                    InvoiceDocument.objects.filter(uploaded_by=request.user, is_duplicate=False)
                    .exclude(pk=doc.pk)
                    .order_by("-upload_date")
                    .first()
                )
                if canonical:
                    merge_duplicate_into_canonical(doc, canonical)
                    emit_document_event("document.duplicate_detected", doc, {"source": "bulk_action"})
                    changed += 1
            elif action == BatchAuditActionForm.ACTION_ASSIGN_CATEGORY:
                extracted = getattr(doc, "extracted", None)
                if extracted and category:
                    extracted.category = category
                    extracted.save(update_fields=["category"])
                    changed += 1
            elif action == BatchAuditActionForm.ACTION_ARCHIVE:
                doc.status = DocumentStatus.VERIFIED
                if not doc.verified_at:
                    doc.verified_at = timezone.now()
                doc.save(update_fields=["status", "verified_at"])
                changed += 1
        messages.success(request, f"Applied '{action}' to {changed} document(s).")
        return redirect("documents:audit_queue")


class DocumentActivityView(LoginRequiredMixin, DetailView):
    """Read-only field-level corrections for one document (AuditLog)."""

    model = InvoiceDocument
    template_name = "documents/document_activity.html"
    context_object_name = "document"
    pk_url_kwarg = "pk"

    def get_queryset(self):
        return InvoiceDocument.objects.filter(uploaded_by=self.request.user)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["audit_logs"] = (
            AuditLog.objects.filter(document=self.object)
            .select_related("changed_by")
            .order_by("-created_at")
        )
        ctx["extraction_logs"] = list(
            ExtractionLog.objects.filter(document=self.object).order_by("-created_at")[:80]
        )
        return ctx


class DocumentReviewView(LoginRequiredMixin, DetailView):
    model = InvoiceDocument
    template_name = "documents/review.html"
    context_object_name = "document"
    pk_url_kwarg = "pk"

    def get_queryset(self):
        return InvoiceDocument.objects.filter(uploaded_by=self.request.user)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        doc: InvoiceDocument = self.object
        extracted, _ = ExtractedData.objects.get_or_create(document=doc)
        if self.request.POST:
            ctx["form"] = ExtractedDataForm(
                self.request.POST, instance=extracted, prefix="ext"
            )
            ctx["line_formset"] = LineItemFormSet(
                self.request.POST,
                instance=extracted,
                prefix="lines",
            )
        else:
            ctx["form"] = ExtractedDataForm(instance=extracted, prefix="ext")
            ctx["line_formset"] = LineItemFormSet(instance=extracted, prefix="lines")
        ctx["audit"] = run_deterministic_audit(extracted)
        fname = (doc.original_filename or getattr(doc.file, "name", "") or "").lower()
        ctx["is_image"] = fname.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))
        ctx["is_pdf"] = fname.endswith(".pdf")
        ctx["line_audit_by_id"] = _line_audit_map(extracted)
        try:
            ctx["file_size_display"] = f"{doc.file.size / 1024:.1f} KB"
        except OSError:
            ctx["file_size_display"] = ""

        queue_ids = list(
            InvoiceDocument.objects.filter(
                uploaded_by=doc.uploaded_by,
                status__in=[
                    DocumentStatus.PENDING_EXTRACTION,
                    DocumentStatus.AUDIT_REQUIRED,
                ],
            )
            .order_by("-upload_date")
            .values_list("pk", flat=True)
        )
        ctx["review_prev_pk"] = ctx["review_next_pk"] = None
        if doc.pk in queue_ids:
            i = queue_ids.index(doc.pk)
            if i + 1 < len(queue_ids):
                ctx["review_prev_pk"] = queue_ids[i + 1]
            if i > 0:
                ctx["review_next_pk"] = queue_ids[i - 1]
        ctx["extraction_logs"] = list(
            ExtractionLog.objects.filter(document=doc).order_by("-created_at")[:24]
        )
        return ctx

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        extracted, _ = ExtractedData.objects.get_or_create(document=self.object)
        extracted.refresh_from_db()
        old_snapshot = _snapshot_extracted(extracted)

        form = ExtractedDataForm(request.POST, instance=extracted, prefix="ext")
        formset = LineItemFormSet(request.POST, instance=extracted, prefix="lines")
        if not (form.is_valid() and formset.is_valid()):
            ctx = self.get_context_data()
            ctx["form"] = form
            ctx["line_formset"] = formset
            ctx["audit"] = run_deterministic_audit(extracted)
            return self.render_to_response(ctx)

        extracted = form.save(commit=False)
        formset.instance = extracted
        formset.save()
        extracted.save()

        extracted.refresh_from_db()
        new_snapshot = _snapshot_extracted(extracted)
        _write_audit_logs(request.user, self.object, old_snapshot, new_snapshot)

        force = form.cleaned_data.get("force_verify", False)
        extracted = ExtractedData.objects.prefetch_related("line_items").get(pk=extracted.pk)
        audit = run_deterministic_audit(extracted)
        if audit["all_ok"] or force:
            self.object.status = DocumentStatus.VERIFIED
            if not self.object.verified_at:
                self.object.verified_at = timezone.now()
        else:
            self.object.status = DocumentStatus.AUDIT_REQUIRED
        self.object.save(update_fields=["status", "verified_at"])
        learn_from_audit_logs(self.object.pk)
        if self.object.status == DocumentStatus.VERIFIED:
            emit_document_event("document.verified", self.object, {"source": "manual_review"})
        else:
            emit_document_event("document.audit_required", self.object, {"source": "manual_review"})

        return HttpResponseRedirect(reverse_lazy("documents:audit_queue"))


def _line_audit_map(extracted: ExtractedData) -> dict[int, dict[str, Any]]:
    """Per line item: qty*unit vs line_total for AI suggestion UI."""
    out: dict[int, dict[str, Any]] = {}
    for li in extracted.line_items.order_by("ordering", "id"):
        ok = True
        suggested: str | None = None
        if li.unit_price is not None:
            try:
                qty = li.quantity or Decimal("1")
                expected = qty * li.unit_price
                lt = li.line_total or Decimal("0")
                if abs(expected - lt) > MONEY_EPS:
                    ok = False
                    suggested = str(expected.quantize(Decimal("0.01")))
            except Exception:
                ok = False
        out[li.pk] = {"ok": ok, "suggested": suggested}
    return out


def _snapshot_extracted(obj: ExtractedData) -> dict[str, str]:
    return {
        "vendor_name": obj.vendor_name or "",
        "date_issued": str(obj.date_issued or ""),
        "subtotal": str(obj.subtotal or ""),
        "tax_amount": str(obj.tax_amount or ""),
        "total_amount": str(obj.total_amount or ""),
        "category_id": str(obj.category_id or ""),
    }


def _write_audit_logs(user, document, old: dict[str, str], new: dict[str, str]) -> None:
    for key in old:
        if old.get(key) != new.get(key):
            AuditLog.objects.create(
                document=document,
                field_changed=key,
                original_value_from_ai=old.get(key, ""),
                corrected_value_from_user=new.get(key, ""),
                changed_by=user,
            )


class ExportView(LoginRequiredMixin, FormView):
    template_name = "documents/export.html"
    form_class = ExportForm

    def get_initial(self):
        initial = super().get_initial()
        preset = (self.request.GET.get("preset") or "").strip()
        if preset:
            ep = ExportPreset.objects.filter(user=self.request.user, name=preset).first()
            if ep:
                initial.update(ep.filters or {})
        for key in ("date_from", "date_to"):
            if v := self.request.GET.get(key):
                initial[key] = v
        return initial

    def form_valid(self, form):
        from documents.api.views import stream_verified_csv, stream_verified_xlsx

        df = form.cleaned_data.get("date_from")
        dt = form.cleaned_data.get("date_to")
        preset_name = (form.cleaned_data.get("preset_name") or "").strip()
        if preset_name:
            ExportPreset.objects.update_or_create(
                user=self.request.user,
                name=preset_name,
                defaults={
                    "filters": {
                        "date_from": df.isoformat() if df else "",
                        "date_to": dt.isoformat() if dt else "",
                        "export_format": form.cleaned_data.get("export_format"),
                    }
                },
            )
        if form.cleaned_data.get("export_format") == ExportForm.FORMAT_XLSX:
            return stream_verified_xlsx(self.request.user, df, dt)
        return stream_verified_csv(self.request.user, df, dt)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["presets"] = ExportPreset.objects.filter(user=self.request.user).order_by("name")
        return ctx


class SettingsView(LoginRequiredMixin, FormView):
    template_name = "documents/settings.html"
    form_class = SystemSettingsForm
    success_url = reverse_lazy("documents:settings")
    tabs = (
        ("general", "General"),
        ("models", "Models"),
        ("crewai", "CrewAI Advanced"),
        ("runtime", "Runtime & Logs"),
        ("management", "Management"),
    )

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = load_ollama_runtime()
        return kwargs

    def post(self, request, *args, **kwargs):
        if request.POST.get("create_api_key"):
            return self._create_api_key(request)
        if request.POST.get("revoke_api_key"):
            return self._revoke_api_key(request)
        if request.POST.get("create_webhook"):
            return self._create_webhook(request)
        if request.POST.get("delete_webhook"):
            return self._delete_webhook(request)
        return super().post(request, *args, **kwargs)

    def _create_api_key(self, request):
        if not request.user.is_superuser:
            messages.error(request, "Admin access required.")
            return redirect("documents:settings")
        raw = ApiKey.build_raw_key()
        prefix = raw[:12]
        key = ApiKey.objects.create(
            name=f"Key {timezone.now().strftime('%Y-%m-%d %H:%M')}",
            key_prefix=prefix,
            key_hash=ApiKey.hash_key(raw),
            created_by=request.user,
            scopes=["documents:read", "documents:write"],
        )
        request.session["new_api_key_once"] = raw
        messages.success(request, f"API key created: {key.key_prefix}... (copy now).")
        return redirect("documents:settings")

    def _revoke_api_key(self, request):
        if not request.user.is_superuser:
            messages.error(request, "Admin access required.")
            return redirect("documents:settings")
        raw_id = request.POST.get("revoke_api_key")
        if str(raw_id).isdigit():
            key = ApiKey.objects.filter(pk=int(raw_id)).first()
            if key:
                key.is_active = False
                key.revoked_at = timezone.now()
                key.save(update_fields=["is_active", "revoked_at"])
                messages.success(request, "API key revoked.")
        return redirect("documents:settings")

    def _create_webhook(self, request):
        if not request.user.is_superuser:
            messages.error(request, "Admin access required.")
            return redirect("documents:settings")
        form = WebhookEndpointForm(request.POST)
        if form.is_valid():
            endpoint = form.save(commit=False)
            endpoint.created_by = request.user
            if not endpoint.signing_secret:
                endpoint.signing_secret = secrets.token_hex(24)
            endpoint.save()
            messages.success(request, "Webhook endpoint created.")
        else:
            messages.error(request, "Invalid webhook configuration.")
        return redirect("documents:settings")

    def _delete_webhook(self, request):
        if not request.user.is_superuser:
            messages.error(request, "Admin access required.")
            return redirect("documents:settings")
        raw_id = request.POST.get("delete_webhook")
        if str(raw_id).isdigit():
            WebhookEndpoint.objects.filter(pk=int(raw_id)).delete()
            messages.success(request, "Webhook endpoint deleted.")
        return redirect("documents:settings")

    def form_valid(self, form):
        self.object = form.save()
        refresh_capabilities_after_save(self.object)
        messages.success(
            self.request,
            "Model-server settings saved. Model capabilities were refreshed from the server.",
        )
        return super().form_valid(form)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        requested_tab = (self.request.GET.get("tab") or "general").strip().lower()
        valid_tabs = {slug for slug, _ in self.tabs}
        active_tab = requested_tab if requested_tab in valid_tabs else "general"
        ctx["ollama_health"] = check_ollama_tags()
        ctx["system_settings"] = ctx["form"].instance
        ctx["settings_tabs"] = self.tabs
        ctx["active_settings_tab"] = active_tab
        ctx["active_settings_partial"] = f"documents/settings_tabs/{active_tab}.html"
        ctx["runtime_logs_sample"] = list(
            AIRuntimeLog.objects.all().order_by("-created_at")[:8]
        )
        ctx["api_keys"] = ApiKey.objects.all().select_related("created_by").order_by("-created_at")[:20]
        ctx["new_api_key_once"] = self.request.session.pop("new_api_key_once", "")
        ctx["webhooks"] = WebhookEndpoint.objects.all().order_by("name")
        ctx["webhook_form"] = WebhookEndpointForm()
        return ctx


class ReportView(LoginRequiredMixin, TemplateView):
    template_name = "documents/report.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        form = DateRangeForm(self.request.GET or None)
        ctx["filter_form"] = form
        if form.is_valid():
            df = form.cleaned_data.get("date_from")
            dt = form.cleaned_data.get("date_to")
        else:
            df = dt = None
        rows = verified_category_breakdown(self.request.user, df, dt)
        ctx["rows"] = rows
        ctx["spend_trend"] = spend_trend(self.request.user, days=90)
        ctx["audit_kpis"] = audit_kpis(self.request.user)
        ctx["sla_metrics"] = sla_metrics(self.request.user)
        max_pct = max((r["pct"] for r in rows), default=0) or 1
        ctx["chart_rows"] = [
            {**r, "bar_width_pct": round(100.0 * r["pct"] / max_pct, 1)} for r in rows
        ]
        return ctx
