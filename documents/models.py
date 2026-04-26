from decimal import Decimal
import hashlib
import secrets

from django.conf import settings
from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    is_system_generated = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class DocumentStatus(models.TextChoices):
    PENDING_EXTRACTION = "pending_extraction", "Pending AI"
    AUDIT_REQUIRED = "audit_required", "Needs Audit"
    VERIFIED = "verified", "Verified"


class InvoiceDocument(models.Model):
    file = models.FileField(upload_to="invoices/%Y/%m/")
    original_filename = models.CharField(max_length=512, blank=True)
    upload_date = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="invoice_documents",
    )
    status = models.CharField(
        max_length=32,
        choices=DocumentStatus.choices,
        default=DocumentStatus.PENDING_EXTRACTION,
        db_index=True,
    )
    confidence_score = models.FloatField(null=True, blank=True)
    extraction_error = models.TextField(blank=True)
    file_sha256 = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="SHA256 digest of the uploaded file bytes for duplicate detection.",
    )
    duplicate_group = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Logical duplicate cluster key.",
    )
    is_duplicate = models.BooleanField(
        default=False,
        db_index=True,
    )
    duplicate_confidence = models.FloatField(
        null=True,
        blank=True,
        help_text="Similarity score when marked as duplicate.",
    )
    canonical_document = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="duplicates",
    )
    duplicate_reason = models.CharField(max_length=255, blank=True)
    extraction_attempts = models.PositiveIntegerField(
        default=0,
        help_text="Total extraction attempts performed for this document.",
    )
    last_rescan_reason = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Latest reason a rescan/retry was triggered.",
    )
    first_processing_started_at = models.DateTimeField(null=True, blank=True)
    last_processing_started_at = models.DateTimeField(null=True, blank=True)
    last_processing_finished_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-upload_date"]
        indexes = [
            models.Index(fields=["status", "-upload_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.original_filename or self.pk} ({self.status})"

    def set_file_hash(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        self.file_sha256 = digest
        if not self.duplicate_group:
            self.duplicate_group = digest[:20]
        return digest


class ExtractedData(models.Model):
    DOCUMENT_TYPE_RECEIPT = "receipt"
    DOCUMENT_TYPE_INVOICE = "invoice"
    DOCUMENT_TYPE_UNKNOWN = "unknown"
    DOCUMENT_TYPE_CHOICES = (
        (DOCUMENT_TYPE_RECEIPT, "Receipt"),
        (DOCUMENT_TYPE_INVOICE, "Invoice"),
        (DOCUMENT_TYPE_UNKNOWN, "Unknown"),
    )

    document = models.OneToOneField(
        InvoiceDocument,
        on_delete=models.CASCADE,
        related_name="extracted",
    )
    vendor_name = models.CharField(max_length=512, blank=True)
    date_issued = models.DateField(null=True, blank=True, db_index=True)
    invoice_number = models.CharField(max_length=128, blank=True, db_index=True)
    document_type = models.CharField(
        max_length=16,
        choices=DOCUMENT_TYPE_CHOICES,
        default=DOCUMENT_TYPE_UNKNOWN,
        db_index=True,
    )
    subtotal = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    tax_amount = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    total_amount = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="extracted_rows",
    )
    raw_json = models.JSONField(null=True, blank=True)
    ollama_model_used = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name_plural = "extracted data"

    def __str__(self) -> str:
        return f"Extracted for doc {self.document_id}"


class LineItem(models.Model):
    extracted = models.ForeignKey(
        ExtractedData,
        on_delete=models.CASCADE,
        related_name="line_items",
    )
    description = models.CharField(max_length=1024, blank=True)
    quantity = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal("1")
    )
    unit_price = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True
    )
    line_total = models.DecimalField(max_digits=14, decimal_places=2)
    ordering = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordering", "id"]


class SystemSettings(models.Model):
    """
    Singleton (pk=1) for server-side Ollama configuration.
    Replaces .env-based OLLAMA_* for runtime behavior.
    """

    ollama_base_url = models.CharField(
        max_length=512,
        default="http://127.0.0.1:11434",
        help_text="Ollama API base URL (no trailing slash required).",
    )
    text_model_base_url = models.CharField(
        max_length=512,
        default="http://127.0.0.1:11434",
        help_text="Legacy per-role endpoint (unused in Ollama single-server mode).",
    )
    vision_model_base_url = models.CharField(
        max_length=512,
        default="http://127.0.0.1:11435",
        help_text="Legacy per-role endpoint (unused in Ollama single-server mode).",
    )
    ollama_vision_model = models.CharField(
        max_length=256,
        default="llava:latest",
        help_text="Model used for image / PDF page vision extraction.",
    )
    ollama_text_model = models.CharField(
        max_length=256,
        default="llama3:latest",
        help_text="Model used for text-only JSON extraction.",
    )
    ollama_ocr_model = models.CharField(
        "OCR model (optional)",
        max_length=256,
        blank=True,
        default="",
        help_text=(
            "Plain-text OCR from images, e.g. glm-ocr:latest. When set, OCR uses this model "
            "instead of the vision model and does not require vision_model_supports_vision. "
            "Leave blank to OCR with the vision model."
        ),
    )
    use_vision_extraction = models.BooleanField(
        default=True,
        help_text="When True, try vision path first for images and PDFs if the vision model supports images.",
    )
    auto_start_model_server = models.BooleanField(
        default=False,
        help_text="Legacy setting (unused in Ollama mode).",
    )
    model_server_start_command = models.TextField(
        blank=True,
        default="",
        help_text="Legacy setting (unused in Ollama mode).",
    )
    model_server_start_timeout_seconds = models.PositiveIntegerField(
        default=45,
        help_text="Legacy setting (unused in Ollama mode).",
    )
    text_model_server_start_command = models.TextField(
        blank=True,
        default="",
        help_text="Legacy setting (unused in Ollama mode).",
    )
    vision_model_server_start_command = models.TextField(
        blank=True,
        default="",
        help_text="Legacy setting (unused in Ollama mode).",
    )
    vision_model_supports_vision = models.BooleanField(
        default=True,
        help_text="Auto-detected: vision model accepts image input (/api/show capabilities or name heuristic).",
    )
    text_model_supports_tools = models.BooleanField(
        default=False,
        help_text="Auto-detected: text model exposes tools capability (for future tool use).",
    )
    use_crewai_hints = models.BooleanField(
        default=True,
        help_text="Enable CrewAI stage hints before text structuring.",
    )
    crew_read_model = models.CharField(
        max_length=256,
        blank=True,
        default="",
        help_text="Model for Crew read stage (blank = ollama_text_model).",
    )
    crew_structure_model = models.CharField(
        max_length=256,
        blank=True,
        default="",
        help_text="Model for Crew structure stage (blank = ollama_text_model).",
    )
    crew_validate_model = models.CharField(
        max_length=256,
        blank=True,
        default="",
        help_text="Model for Crew validate stage (blank = ollama_text_model).",
    )
    crew_category_model = models.CharField(
        max_length=256,
        blank=True,
        default="",
        help_text="Model for Crew category stage (blank = ollama_text_model).",
    )
    crew_stage_timeout_seconds = models.PositiveIntegerField(
        default=45,
        help_text="Per-stage timeout budget for Crew operations.",
    )
    crew_max_retries = models.PositiveIntegerField(
        default=2,
        help_text="Retries per Crew stage when transient errors occur.",
    )
    crew_hint_max_chars = models.PositiveIntegerField(
        default=1200,
        help_text="Maximum guidance text length from Crew stages.",
    )
    max_document_rescan_attempts = models.PositiveIntegerField(
        default=2,
        help_text="Maximum full OCR rescan + re-audit attempts per document.",
    )
    rescan_backoff_seconds = models.PositiveIntegerField(
        default=0,
        help_text="Delay between automatic rescan attempts in seconds.",
    )
    enable_duplicate_detection = models.BooleanField(
        default=True,
        help_text="When enabled, mark and cluster likely duplicate receipts.",
    )
    enable_webhooks = models.BooleanField(
        default=True,
        help_text="When enabled, lifecycle events are delivered to webhook endpoints.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "system settings"
        verbose_name_plural = "system settings"

    def __str__(self) -> str:
        return "System settings"


class ExtractionLog(models.Model):
    """Append-only pipeline log for one document (Ollama path, audit, errors)."""

    class Level(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"

    document = models.ForeignKey(
        InvoiceDocument,
        on_delete=models.CASCADE,
        related_name="extraction_logs",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    level = models.CharField(max_length=16, choices=Level.choices, default=Level.INFO)
    event = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Short machine key, e.g. extraction_started, vision_ok.",
    )
    message = models.TextField()
    details = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["document", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.event or self.level} @ {self.created_at}"


class AuditLog(models.Model):
    document = models.ForeignKey(
        InvoiceDocument,
        on_delete=models.CASCADE,
        related_name="audit_logs",
    )
    field_changed = models.CharField(max_length=255)
    original_value_from_ai = models.TextField(blank=True)
    corrected_value_from_user = models.TextField(blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class AIRuntimeLog(models.Model):
    class Level(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    role = models.CharField(
        max_length=16,
        db_index=True,
        help_text="text | vision | ocr",
    )
    level = models.CharField(max_length=16, choices=Level.choices, default=Level.INFO)
    event = models.CharField(max_length=64, db_index=True)
    model = models.CharField(max_length=255, blank=True)
    base_url = models.CharField(max_length=512, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    message = models.TextField(blank=True)
    details = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class VendorProfile(models.Model):
    vendor_key = models.CharField(max_length=255, unique=True)
    display_name = models.CharField(max_length=512, blank=True)
    default_category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vendor_profiles",
    )
    date_format_hint = models.CharField(max_length=32, blank=True)
    tax_label_hint = models.CharField(max_length=64, blank=True)
    extraction_hints = models.JSONField(default=dict, blank=True)
    correction_count = models.PositiveIntegerField(default=0)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["vendor_key"]

    def __str__(self) -> str:
        return self.display_name or self.vendor_key


class ApiKey(models.Model):
    name = models.CharField(max_length=128)
    key_prefix = models.CharField(max_length=16, unique=True)
    key_hash = models.CharField(max_length=128, unique=True)
    scopes = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.key_prefix})"

    @staticmethod
    def build_raw_key() -> str:
        return f"ors_{secrets.token_urlsafe(32)}"

    @staticmethod
    def hash_key(raw_key: str) -> str:
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class WebhookEndpoint(models.Model):
    EVENT_CHOICES = [
        ("document.verified", "Document verified"),
        ("document.audit_required", "Document requires audit"),
        ("document.failed", "Document failed extraction"),
        ("document.duplicate_detected", "Duplicate detected"),
    ]

    name = models.CharField(max_length=128)
    target_url = models.URLField(max_length=500)
    signing_secret = models.CharField(max_length=128)
    subscribed_events = models.JSONField(
        default=list,
        blank=True,
        help_text="List of event names to deliver.",
    )
    is_active = models.BooleanField(default=True)
    failure_count = models.PositiveIntegerField(default=0)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    timeout_seconds = models.PositiveIntegerField(default=10)
    max_retries = models.PositiveIntegerField(default=2)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="webhook_endpoints",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self) -> str:
        return self.name


class ExportPreset(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="export_presets",
    )
    name = models.CharField(max_length=64)
    filters = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "name")
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.name}"
