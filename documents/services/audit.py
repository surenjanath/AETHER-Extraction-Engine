"""Deterministic math and type checks for extracted invoice data."""

from __future__ import annotations

from decimal import Decimal
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from documents.models import ExtractedData

MONEY_EPS = Decimal("0.02")


def _sum_line_items(extracted: ExtractedData) -> Decimal:
    total = Decimal("0")
    for li in extracted.line_items.all():
        total += li.line_total or Decimal("0")
    return total


def run_deterministic_audit(extracted: ExtractedData) -> dict[str, Any]:
    """
    Returns dict with keys:
      line_sum_ok, tax_total_ok, parse_ok, messages (list str)
    """
    messages: list[str] = []
    parse_ok = True

    if extracted.date_issued is None and not extracted.vendor_name:
        parse_ok = False
        messages.append("Missing vendor and date")

    invoice_number = (extracted.invoice_number or "").strip()
    if invoice_number and (len(invoice_number) > 80 or re.fullmatch(r"[\W_]+", invoice_number)):
        parse_ok = False
        messages.append("Invoice number appears malformed")

    sub = extracted.subtotal
    tax = extracted.tax_amount or Decimal("0")
    tot = extracted.total_amount
    line_sum = _sum_line_items(extracted)

    line_sum_ok = True
    if extracted.line_items.exists():
        if sub is not None:
            if abs(line_sum - sub) > MONEY_EPS:
                line_sum_ok = False
                messages.append(
                    f"Line items sum {line_sum} != subtotal {sub} (tolerance {MONEY_EPS})"
                )
        else:
            line_sum_ok = False
            messages.append("Line items present but subtotal missing")

    tax_total_ok = True
    if sub is not None and tot is not None:
        expected = sub + tax
        if abs(expected - tot) > MONEY_EPS:
            tax_total_ok = False
            messages.append(
                f"Subtotal+Tax {expected} != total {tot} (tolerance {MONEY_EPS})"
            )
    elif tot is not None and (sub is None):
        parse_ok = False
        messages.append("Total without subtotal")

    return {
        "line_sum_ok": line_sum_ok,
        "tax_total_ok": tax_total_ok,
        "parse_ok": parse_ok,
        "messages": messages,
        "all_ok": line_sum_ok and tax_total_ok and parse_ok,
    }
