"""Pydantic schemas for strict Ollama JSON extraction."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar, Optional

from pydantic import BaseModel, Field, field_validator


class LineItemSchema(BaseModel):
    description: str = ""
    quantity: Decimal = Field(default=Decimal("1"))
    unit_price: Optional[Decimal] = None
    line_total: Decimal

    @field_validator("quantity", "unit_price", "line_total", mode="before")
    @classmethod
    def coerce_decimal(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        return v

    @field_validator("quantity", mode="before")
    @classmethod
    def default_quantity_when_missing(cls, v: Any) -> Any:
        if v is None or v == "":
            return Decimal("1")
        return v


class ExtractionSchema(BaseModel):
    DOCUMENT_TYPE_ALLOWED: ClassVar[set[str]] = {"receipt", "invoice", "unknown"}

    vendor_name: str = ""
    date_issued: Optional[date] = None
    invoice_number: Optional[str] = None
    document_type: str = "unknown"
    subtotal: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    total_amount: Optional[Decimal] = None
    line_items: list[LineItemSchema] = Field(default_factory=list)

    @field_validator(
        "subtotal", "tax_amount", "total_amount", mode="before"
    )
    @classmethod
    def coerce_optional_decimal(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        return v

    @field_validator("vendor_name", mode="before")
    @classmethod
    def coerce_vendor_name(cls, v: Any) -> str:
        if v is None:
            return ""
        text = str(v).strip()
        if not text:
            return ""

        up = text.upper()
        # Guard against common OCR/model mistakes where date header text
        # ("DATE 06/01/2016 WED") is emitted as vendor_name.
        if "DATE" in up:
            return ""
        if re.search(r"\b(MON|TUE|WED|THU|FRI|SAT|SUN)\b", up):
            return ""
        if re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", up):
            return ""
        return text

    @field_validator("invoice_number", mode="before")
    @classmethod
    def coerce_invoice_number(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        text = str(v).strip()
        if not text:
            return None
        # reject obvious noisy payloads
        if len(text) > 80:
            return None
        if re.fullmatch(r"[\W_]+", text):
            return None
        # Avoid plain words like "East" being treated as invoice numbers.
        if not (re.search(r"\d", text) or "-" in text or "/" in text):
            return None
        return text

    @field_validator("document_type", mode="before")
    @classmethod
    def normalize_document_type(cls, v: Any) -> str:
        raw = str(v or "").strip().lower()
        if raw in cls.DOCUMENT_TYPE_ALLOWED:
            return raw
        return "unknown"


EXTRACTION_JSON_INSTRUCTIONS = """
Return ONLY a single JSON object (no markdown fences) with exactly these keys:
- vendor_name: string
- date_issued: string ISO date YYYY-MM-DD, or null if unknown (convert MM/DD/YY to 20YY-MM-DD when confident)
- invoice_number: string or null (if you see labels like Invoice No / Inv # / Bill No)
- document_type: one of "receipt", "invoice", or "unknown"
- subtotal: number or null
- tax_amount: number or null
- total_amount: number or null
- line_items: array of objects, each with:
  - description: string
  - quantity: number (default 1)
  - unit_price: number or null
  - line_total: number (required per line)

Text may be noisy wrapped OCR: read SUBTOTAL / TAX / TOTAL / AMOUNT DUE lines carefully.
Do NOT hallucinate line_items. If uncertain, return fewer lines (or empty array) rather than guessing.
Prefer correct subtotal/tax/total over exhaustive line_items.
Keep line_items to concrete purchase rows only; exclude payment lines, change, loyalty text,
store metadata, coupons without amounts, and pure OCR gibberish.
Use null where a value cannot be read. Numbers must be JSON numbers, not strings.
If the receipt body is truncated, prefer correct subtotal/tax/total over filling line_items.
"""
