from __future__ import annotations

import re

from django.db.models import Count
from django.utils import timezone

from documents.models import AuditLog, Category, ExtractedData, VendorProfile


def normalize_vendor_key(vendor_name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", (vendor_name or "").strip().lower())
    return cleaned.strip("_")[:200] or "unknown_vendor"


def update_vendor_profile_from_extracted(extracted: ExtractedData) -> VendorProfile:
    key = normalize_vendor_key(extracted.vendor_name or "")
    profile, _ = VendorProfile.objects.get_or_create(
        vendor_key=key,
        defaults={"display_name": extracted.vendor_name or key},
    )
    profile.last_seen_at = timezone.now()
    if extracted.vendor_name and not profile.display_name:
        profile.display_name = extracted.vendor_name
    if extracted.category_id and not profile.default_category_id:
        profile.default_category = extracted.category
    profile.save(
        update_fields=[
            "last_seen_at",
            "display_name",
            "default_category",
            "updated_at",
        ]
    )
    return profile


def learn_from_audit_logs(document_id: int) -> None:
    logs = AuditLog.objects.filter(document_id=document_id).values("field_changed").annotate(n=Count("id"))
    if not logs:
        return
    extracted = ExtractedData.objects.filter(document_id=document_id).select_related("category").first()
    if not extracted:
        return
    profile = update_vendor_profile_from_extracted(extracted)
    hints = dict(profile.extraction_hints or {})
    for row in logs:
        field = row["field_changed"]
        hints[field] = hints.get(field, 0) + int(row["n"] or 0)
    profile.correction_count = sum(v for v in hints.values() if isinstance(v, int))
    if extracted.category_id:
        profile.default_category = extracted.category
    profile.extraction_hints = hints
    profile.save(update_fields=["extraction_hints", "correction_count", "default_category", "updated_at"])


def profile_prompt_hints(vendor_name: str) -> str:
    key = normalize_vendor_key(vendor_name)
    profile = VendorProfile.objects.filter(vendor_key=key).select_related("default_category").first()
    if not profile:
        return ""
    parts: list[str] = []
    if profile.default_category:
        parts.append(f"Prefer category '{profile.default_category.name}' when ambiguous.")
    common_fix = sorted(
        [
            (k, v)
            for k, v in (profile.extraction_hints or {}).items()
            if isinstance(v, int)
        ],
        key=lambda x: x[1],
        reverse=True,
    )[:3]
    if common_fix:
        fields = ", ".join(k for k, _ in common_fix)
        parts.append(f"Historically corrected fields for this vendor: {fields}.")
    return " ".join(parts).strip()

