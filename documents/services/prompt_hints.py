"""Optional few-shot hints from past user corrections (AuditLog)."""

from __future__ import annotations

from documents.models import AuditLog


def build_correction_hints(max_lines: int = 6) -> str:
    logs = (
        AuditLog.objects.select_related("document")
        .order_by("-created_at")[:max_lines]
    )
    parts: list[str] = []
    for log in logs:
        parts.append(
            f"- field {log.field_changed}: was {log.original_value_from_ai!r} "
            f"corrected to {log.corrected_value_from_user!r}"
        )
    if not parts:
        return ""
    return "Past user corrections (trust document over these if conflict):\n" + "\n".join(parts)
