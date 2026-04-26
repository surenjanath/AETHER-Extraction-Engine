"""Vendor-based category matching with optional Ollama classification."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Optional, Tuple

import httpx

from documents.models import Category
from documents.services.runtime_ollama import load_ollama_runtime

if TYPE_CHECKING:
    from documents.models import ExtractedData

logger = logging.getLogger(__name__)

# vendor substring (lowercase) -> category name
VENDOR_KEYWORDS: list[tuple[str, str]] = [
    ("home depot", "Hardware / Maintenance"),
    ("lowe", "Hardware / Maintenance"),
    ("amazon", "Software / Subscriptions"),
    ("microsoft", "Software / Subscriptions"),
    ("uber", "Travel & Transport"),
    ("lyft", "Travel & Transport"),
    ("starbucks", "Meals & Entertainment"),
    ("restaurant", "Meals & Entertainment"),
    ("cafe", "Meals & Entertainment"),
    ("shell", "Fuel & Auto"),
    ("bp ", "Fuel & Auto"),
    ("exxon", "Fuel & Auto"),
]


def _normalize_vendor(vendor: str) -> str:
    return re.sub(r"\s+", " ", (vendor or "").lower()).strip()


def match_category_by_vendor(vendor: str) -> Optional[Category]:
    nv = _normalize_vendor(vendor)
    for needle, cat_name in VENDOR_KEYWORDS:
        if needle in nv:
            cat = Category.objects.filter(name__iexact=cat_name).first()
            if cat:
                return cat
    return Category.objects.filter(name__icontains=nv[:20]).first() if nv else None


def classify_with_ollama(vendor: str, line_summary: str) -> tuple[Optional[str], bool]:
    """
    Ask Ollama to pick an existing category name or return NEW:<name>.
    Returns (category_name_or_none, used_llm).
    """
    names = list(Category.objects.filter(is_system_generated=False).values_list("name", flat=True))
    if not names:
        return None, False
    allowed = "\n".join(f"- {n}" for n in names)
    prompt = (
        f"Vendor: {vendor}\nSummary: {line_summary[:500]}\n\n"
        f"Pick exactly one category from this list ONLY (copy the name exactly):\n{allowed}\n\n"
        "If none fit, respond with exactly: NEW:YourCategoryName (short name, no JSON).\n"
        "Respond with a single line only."
    )
    try:
        rt = load_ollama_runtime()
        base = rt.ollama_base_url.rstrip("/")
        url = f"{base}/api/generate"
        payload = {
            "model": rt.ollama_text_model,
            "prompt": prompt,
            "stream": False,
        }
        with httpx.Client(timeout=60.0) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
            line = (r.json().get("response") or "").strip().splitlines()[0].strip()
        if line.upper().startswith("NEW:"):
            return line.split(":", 1)[1].strip(), True
        for n in names:
            if n.lower() == line.lower():
                return n, True
        # fuzzy contains
        for n in names:
            if n.lower() in line.lower():
                return n, True
    except Exception as exc:
        logger.warning("Ollama classification failed: %s", exc)
    return None, False


def assign_category(extracted: ExtractedData) -> Tuple[Optional[Category], str]:
    """
    Returns (Category or None, reason).
    """
    vendor = extracted.vendor_name or ""
    by_kw = match_category_by_vendor(vendor)
    if by_kw:
        return by_kw, "keyword_vendor_match"

    summary = " ".join(li.description for li in extracted.line_items.all()[:5])
    name, used = classify_with_ollama(vendor, summary)
    if not name:
        return None, "no_match"

    cat = Category.objects.filter(name__iexact=name).first()
    if cat:
        return cat, "ollama_existing" if used else "exact"

    new_cat = Category.objects.create(
        name=name[:255],
        description="System proposed from extraction",
        is_system_generated=True,
    )
    return new_cat, "ollama_new_category"


def heuristic_confidence(audit: dict, has_category: bool) -> float:
    if not audit.get("parse_ok"):
        return 0.0
    if audit.get("all_ok") and has_category:
        return 1.0
    if audit.get("all_ok"):
        return 0.75
    return 0.5
