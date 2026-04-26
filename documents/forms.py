from django import forms
from django.forms import inlineformset_factory

from documents.models import (
    Category,
    DocumentStatus,
    ExportPreset,
    ExtractedData,
    LineItem,
    SystemSettings,
    WebhookEndpoint,
)

TW_INPUT = (
    "w-full rounded-DEFAULT border border-outline-variant bg-surface-container-low "
    "px-3 py-2 font-body-md text-body-md text-on-surface placeholder:text-on-surface-variant "
    "focus:border-outline focus:outline-none focus:ring-1 focus:ring-outline/30"
)
TW_SELECT = TW_INPUT + " appearance-none"
TW_CHECK = "h-5 w-5 rounded-sm border-2 border-on-surface-variant bg-surface text-primary accent-primary focus:ring-2 focus:ring-outline"


class SystemSettingsForm(forms.ModelForm):
    """Ollama configuration stored in the database (Settings page)."""

    class Meta:
        model = SystemSettings
        fields = (
            "ollama_base_url",
            "ollama_ocr_model",
            "ollama_text_model",
            "use_vision_extraction",
            "use_crewai_hints",
            "crew_read_model",
            "crew_structure_model",
            "crew_validate_model",
            "crew_category_model",
            "crew_stage_timeout_seconds",
            "crew_max_retries",
            "crew_hint_max_chars",
            "max_document_rescan_attempts",
            "rescan_backoff_seconds",
        )
        widgets = {
            "ollama_base_url": forms.TextInput(
                attrs={
                    "class": TW_INPUT,
                    "placeholder": "http://127.0.0.1:11434",
                    "autocomplete": "off",
                }
            ),
            "ollama_ocr_model": forms.TextInput(
                attrs={
                    "class": TW_INPUT,
                    "placeholder": "e.g. glm-ocr:latest (plain-text OCR; optional)",
                    "list": "ollama-model-names",
                }
            ),
            "ollama_text_model": forms.TextInput(
                attrs={
                    "class": TW_INPUT,
                    "placeholder": "e.g. llama3:latest",
                    "list": "ollama-model-names",
                }
            ),
            "use_vision_extraction": forms.CheckboxInput(attrs={"class": TW_CHECK}),
            "use_crewai_hints": forms.CheckboxInput(attrs={"class": TW_CHECK}),
            "crew_read_model": forms.TextInput(
                attrs={
                    "class": TW_INPUT,
                    "placeholder": "blank = use ollama_text_model",
                    "list": "ollama-model-names",
                }
            ),
            "crew_structure_model": forms.TextInput(
                attrs={
                    "class": TW_INPUT,
                    "placeholder": "blank = use ollama_text_model",
                    "list": "ollama-model-names",
                }
            ),
            "crew_validate_model": forms.TextInput(
                attrs={
                    "class": TW_INPUT,
                    "placeholder": "blank = use ollama_text_model",
                    "list": "ollama-model-names",
                }
            ),
            "crew_category_model": forms.TextInput(
                attrs={
                    "class": TW_INPUT,
                    "placeholder": "blank = use ollama_text_model",
                    "list": "ollama-model-names",
                }
            ),
            "crew_stage_timeout_seconds": forms.NumberInput(
                attrs={
                    "class": TW_INPUT,
                    "min": "5",
                    "max": "180",
                    "step": "1",
                }
            ),
            "crew_max_retries": forms.NumberInput(
                attrs={
                    "class": TW_INPUT,
                    "min": "0",
                    "max": "5",
                    "step": "1",
                }
            ),
            "crew_hint_max_chars": forms.NumberInput(
                attrs={
                    "class": TW_INPUT,
                    "min": "200",
                    "max": "6000",
                    "step": "100",
                }
            ),
            "max_document_rescan_attempts": forms.NumberInput(
                attrs={
                    "class": TW_INPUT,
                    "min": "0",
                    "max": "8",
                    "step": "1",
                }
            ),
            "rescan_backoff_seconds": forms.NumberInput(
                attrs={
                    "class": TW_INPUT,
                    "min": "0",
                    "max": "30",
                    "step": "1",
                }
            ),
        }


class DateRangeForm(forms.Form):
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": TW_INPUT}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": TW_INPUT}),
    )


class ExportForm(DateRangeForm):
    FORMAT_CSV = "csv"
    FORMAT_XLSX = "xlsx"
    export_format = forms.ChoiceField(
        label="Format",
        choices=[(FORMAT_CSV, "CSV"), (FORMAT_XLSX, "Excel (.xlsx)")],
        initial=FORMAT_CSV,
        widget=forms.RadioSelect(
            attrs={"class": "space-y-2 text-on-surface [&_input]:border-outline-variant"}
        ),
    )
    preset_name = forms.CharField(
        required=False,
        label="Preset name",
        widget=forms.TextInput(
            attrs={
                "class": TW_INPUT,
                "placeholder": "Optional: save this filter as a preset",
            }
        ),
    )


class ExtractedDataForm(forms.ModelForm):
    force_verify = forms.BooleanField(
        required=False,
        label="Mark verified even if math checks fail",
        help_text="Use only when the receipt is correct but fails automated checks.",
        widget=forms.CheckboxInput(attrs={"class": TW_CHECK}),
    )

    class Meta:
        model = ExtractedData
        fields = [
            "vendor_name",
            "date_issued",
            "invoice_number",
            "document_type",
            "subtotal",
            "tax_amount",
            "total_amount",
            "category",
        ]
        widgets = {
            "vendor_name": forms.TextInput(attrs={"class": TW_INPUT}),
            "date_issued": forms.DateInput(attrs={"type": "date", "class": TW_INPUT}),
            "invoice_number": forms.TextInput(attrs={"class": TW_INPUT}),
            "document_type": forms.Select(attrs={"class": TW_SELECT}),
            "subtotal": forms.NumberInput(attrs={"class": TW_INPUT, "step": "0.01"}),
            "tax_amount": forms.NumberInput(attrs={"class": TW_INPUT, "step": "0.01"}),
            "total_amount": forms.NumberInput(attrs={"class": TW_INPUT, "step": "0.01"}),
            "category": forms.Select(attrs={"class": TW_SELECT}),
        }


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ("name", "description")
        widgets = {
            "name": forms.TextInput(attrs={"class": TW_INPUT, "placeholder": "Category name"}),
            "description": forms.Textarea(
                attrs={
                    "class": TW_INPUT + " min-h-[80px]",
                    "rows": 3,
                    "placeholder": "Optional description",
                }
            ),
        }


class HistoryFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        label="",
        widget=forms.TextInput(
            attrs={
                "class": TW_INPUT,
                "placeholder": "Search vendor, filename…",
            }
        ),
    )
    status = forms.ChoiceField(
        required=False,
        label="Status",
        choices=[
            ("", "All statuses"),
            (DocumentStatus.PENDING_EXTRACTION, "Pending AI"),
            (DocumentStatus.AUDIT_REQUIRED, "Needs audit"),
            (DocumentStatus.VERIFIED, "Verified"),
        ],
        widget=forms.Select(attrs={"class": TW_SELECT}),
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.all().order_by("name"),
        required=False,
        label="Category",
        empty_label="All categories",
        widget=forms.Select(attrs={"class": TW_SELECT}),
    )
    days = forms.ChoiceField(
        required=False,
        label="Date range",
        choices=[
            ("", "All time"),
            ("7", "Last 7 days"),
            ("30", "Last 30 days"),
            ("90", "Last 90 days"),
        ],
        widget=forms.Select(attrs={"class": TW_SELECT}),
    )
    only_duplicates = forms.BooleanField(
        required=False,
        label="Duplicates only",
        widget=forms.CheckboxInput(attrs={"class": TW_CHECK}),
    )


class BatchAuditActionForm(forms.Form):
    ACTION_VERIFY = "verify"
    ACTION_REQUEUE = "requeue"
    ACTION_MARK_DUP = "mark_duplicate"
    ACTION_ASSIGN_CATEGORY = "assign_category"
    ACTION_ARCHIVE = "archive"

    doc_ids = forms.CharField(required=True)
    action = forms.ChoiceField(
        choices=[
            (ACTION_VERIFY, "Verify"),
            (ACTION_REQUEUE, "Requeue"),
            (ACTION_MARK_DUP, "Mark duplicate"),
            (ACTION_ASSIGN_CATEGORY, "Assign category"),
            (ACTION_ARCHIVE, "Archive"),
        ],
        widget=forms.Select(attrs={"class": TW_SELECT}),
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.all().order_by("name"),
        required=False,
        widget=forms.Select(attrs={"class": TW_SELECT}),
    )

    def clean_doc_ids(self):
        raw = self.cleaned_data["doc_ids"]
        ids = []
        for part in raw.split(","):
            p = part.strip()
            if p.isdigit():
                ids.append(int(p))
        if not ids:
            raise forms.ValidationError("Select at least one document.")
        return ids


class WebhookEndpointForm(forms.ModelForm):
    class Meta:
        model = WebhookEndpoint
        fields = (
            "name",
            "target_url",
            "signing_secret",
            "subscribed_events",
            "is_active",
            "timeout_seconds",
            "max_retries",
        )
        widgets = {
            "name": forms.TextInput(attrs={"class": TW_INPUT}),
            "target_url": forms.URLInput(attrs={"class": TW_INPUT}),
            "signing_secret": forms.TextInput(attrs={"class": TW_INPUT}),
            "subscribed_events": forms.TextInput(
                attrs={
                    "class": TW_INPUT,
                    "placeholder": "Comma-separated, e.g. document.verified,document.failed",
                }
            ),
            "is_active": forms.CheckboxInput(attrs={"class": TW_CHECK}),
            "timeout_seconds": forms.NumberInput(attrs={"class": TW_INPUT, "min": "1", "max": "60"}),
            "max_retries": forms.NumberInput(attrs={"class": TW_INPUT, "min": "0", "max": "10"}),
        }

    def clean_subscribed_events(self):
        value = self.cleaned_data.get("subscribed_events")
        if isinstance(value, list):
            return value
        text = str(value or "")
        return [x.strip() for x in text.split(",") if x.strip()]


LineItemFormSet = inlineformset_factory(
    ExtractedData,
    LineItem,
    fields=("description", "quantity", "unit_price", "line_total", "ordering"),
    extra=0,
    can_delete=True,
    min_num=0,
    validate_min=False,
    widgets={
        "ordering": forms.HiddenInput(),
        "description": forms.TextInput(attrs={"class": TW_INPUT}),
        "quantity": forms.NumberInput(attrs={"class": TW_INPUT, "step": "any"}),
        "unit_price": forms.NumberInput(attrs={"class": TW_INPUT, "step": "any"}),
        "line_total": forms.NumberInput(attrs={"class": TW_INPUT, "step": "0.01"}),
    },
)
