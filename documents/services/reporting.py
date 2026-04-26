"""Aggregations for dashboard and reports (verified extractions)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Count, F, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from documents.models import DocumentStatus, ExtractedData


def verified_category_breakdown(
    user,
    date_from=None,
    date_to=None,
) -> list[dict[str, Any]]:
    """
    Rows for category totals among verified documents, with percentage of grand total.
    """
    qs = ExtractedData.objects.filter(
        document__uploaded_by=user,
        document__status=DocumentStatus.VERIFIED,
    )
    if date_from:
        qs = qs.filter(date_issued__gte=date_from)
    if date_to:
        qs = qs.filter(date_issued__lte=date_to)
    rows = list(
        qs.values("category__name")
        .annotate(total=Sum("total_amount"))
        .order_by("-total")
    )
    grand = sum((r["total"] or 0) for r in rows)
    if not grand:
        return [
            {
                "name": r["category__name"] or "Uncategorized",
                "total": r["total"],
                "pct": 0.0,
            }
            for r in rows
        ]
    out = []
    for r in rows:
        t = r["total"] or 0
        out.append(
            {
                "name": r["category__name"] or "Uncategorized",
                "total": t,
                "pct": round(float(t) / float(grand) * 100, 1),
            }
        )
    return out


def spend_trend(user, days: int = 30) -> list[dict[str, Any]]:
    since = timezone.now() - timedelta(days=days)
    qs = (
        ExtractedData.objects.filter(
            document__uploaded_by=user,
            document__status=DocumentStatus.VERIFIED,
            document__upload_date__gte=since,
        )
        .annotate(day=TruncDate("document__upload_date"))
        .values("day")
        .annotate(total=Sum("total_amount"), count=Count("id"))
        .order_by("day")
    )
    return [
        {
            "day": row["day"].isoformat() if row["day"] else "",
            "total": float(row["total"] or 0),
            "count": row["count"],
        }
        for row in qs
    ]


def audit_kpis(user) -> dict[str, Any]:
    total = ExtractedData.objects.filter(document__uploaded_by=user).count()
    no_correction = ExtractedData.objects.filter(
        document__uploaded_by=user,
        document__status=DocumentStatus.VERIFIED,
        document__audit_logs__isnull=True,
    ).count()
    correction_count = ExtractedData.objects.filter(
        document__uploaded_by=user,
        document__audit_logs__isnull=False,
    ).distinct().count()
    rescan_success = ExtractedData.objects.filter(
        document__uploaded_by=user,
        document__status=DocumentStatus.VERIFIED,
        document__extraction_attempts__gt=1,
    ).count()
    return {
        "ai_pass_rate": round((no_correction / total) * 100, 1) if total else 0.0,
        "correction_density": round((correction_count / total) * 100, 1) if total else 0.0,
        "rescan_success_rate": round((rescan_success / total) * 100, 1) if total else 0.0,
    }


def sla_metrics(user) -> dict[str, Any]:
    qs = ExtractedData.objects.filter(
        document__uploaded_by=user,
        document__first_processing_started_at__isnull=False,
        document__last_processing_finished_at__isnull=False,
    ).annotate(
        extract_seconds=F("document__last_processing_finished_at") - F("document__first_processing_started_at"),
    )
    # SQLite timedelta aggregation can be inconsistent; keep robust with Python fallback.
    extract_values = []
    for row in qs.values_list("document__first_processing_started_at", "document__last_processing_finished_at"):
        if row[0] and row[1]:
            extract_values.append((row[1] - row[0]).total_seconds())
    avg_extract = round(sum(extract_values) / len(extract_values), 1) if extract_values else 0.0

    ver_qs = ExtractedData.objects.filter(
        document__uploaded_by=user,
        document__verified_at__isnull=False,
    )
    verify_values = []
    for row in ver_qs.values_list("document__upload_date", "document__verified_at"):
        if row[0] and row[1]:
            verify_values.append((row[1] - row[0]).total_seconds())
    avg_verify = round(sum(verify_values) / len(verify_values), 1) if verify_values else 0.0
    queue_aging = (
        ExtractedData.objects.filter(
            document__uploaded_by=user,
            document__status=DocumentStatus.AUDIT_REQUIRED,
        ).count()
    )
    return {
        "avg_extract_seconds": avg_extract,
        "avg_verify_seconds": avg_verify,
        "queue_aging_count": queue_aging,
    }
