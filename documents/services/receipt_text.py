"""Prepare noisy OCR / receipt text for LLM context windows."""

from __future__ import annotations

# Enough for long register receipts while staying within typical local-model context.
DEFAULT_EXTRACTION_TEXT_BUDGET = 20_000


def prepare_receipt_text_for_llm(
    text: str,
    *,
    budget: int = DEFAULT_EXTRACTION_TEXT_BUDGET,
) -> str:
    """
    If text exceeds ``budget`` characters, keep the start (store header) and end
    (subtotal/tax/total/footer often live here) instead of truncating only the head.
    """
    s = text.strip()
    if len(s) <= budget:
        return s

    marker = (
        "\n\n[... OCR middle omitted for length — store header is above; "
        "subtotal, tax, total, and payment lines are often below ...]\n\n"
    )
    reserve = len(marker) + 64
    if budget <= reserve:
        return s[:budget]

    half = (budget - reserve) // 2
    head_len = min(half, 10_000)
    tail_len = budget - reserve - head_len
    if tail_len < 2000:
        tail_len = 2000
        head_len = max(1000, budget - reserve - tail_len)

    head = s[:head_len]
    tail = s[-tail_len:] if tail_len > 0 else ""
    return f"{head}{marker}{tail}"
