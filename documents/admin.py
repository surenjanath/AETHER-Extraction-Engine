from django.contrib import admin

from documents.models import (
    ApiKey,
    AuditLog,
    Category,
    ExportPreset,
    ExtractedData,
    ExtractionLog,
    InvoiceDocument,
    LineItem,
    SystemSettings,
    VendorProfile,
    WebhookEndpoint,
)


@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "ollama_base_url",
        "ollama_vision_model",
        "ollama_ocr_model",
        "ollama_text_model",
        "use_crewai_hints",
        "use_vision_extraction",
        "auto_start_model_server",
        "vision_model_supports_vision",
        "text_model_supports_tools",
        "updated_at",
    )

    def has_add_permission(self, request):
        return not SystemSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class LineItemInline(admin.TabularInline):
    model = LineItem
    extra = 0


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_system_generated")
    search_fields = ("name",)


class ExtractedDataInline(admin.StackedInline):
    model = ExtractedData
    show_change_link = True


class ExtractionLogInline(admin.TabularInline):
    model = ExtractionLog
    extra = 0
    can_delete = False
    readonly_fields = ("created_at", "level", "event", "message", "details")
    ordering = ("-created_at",)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(InvoiceDocument)
class InvoiceDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "original_filename",
        "uploaded_by",
        "status",
        "confidence_score",
        "upload_date",
    )
    list_filter = ("status",)
    search_fields = ("original_filename",)
    readonly_fields = ("upload_date",)
    inlines = [ExtractedDataInline, ExtractionLogInline]


@admin.register(ExtractedData)
class ExtractedDataAdmin(admin.ModelAdmin):
    list_display = ("document", "vendor_name", "date_issued", "total_amount", "category")
    inlines = [LineItemInline]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("document", "field_changed", "changed_by", "created_at")
    readonly_fields = ("created_at",)


@admin.register(ExtractionLog)
class ExtractionLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "document", "level", "event", "message_preview")
    list_filter = ("level",)
    search_fields = ("message", "event", "document__original_filename")
    readonly_fields = ("created_at", "document", "level", "event", "message", "details")

    @admin.display(description="Message")
    def message_preview(self, obj: ExtractionLog) -> str:
        return (obj.message or "")[:80]

    def has_add_permission(self, request):
        return False


@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display = ("vendor_key", "display_name", "default_category", "correction_count", "last_seen_at")
    search_fields = ("vendor_key", "display_name")


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "key_prefix", "created_by", "is_active", "last_used_at", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "key_prefix")
    readonly_fields = ("key_hash", "key_prefix", "last_used_at", "created_at")


@admin.register(WebhookEndpoint)
class WebhookEndpointAdmin(admin.ModelAdmin):
    list_display = ("name", "target_url", "is_active", "failure_count", "last_sent_at")
    list_filter = ("is_active",)
    search_fields = ("name", "target_url")


@admin.register(ExportPreset)
class ExportPresetAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "updated_at")
    search_fields = ("name", "user__username")
