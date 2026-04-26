from __future__ import annotations

from documents.models import DocumentStatus, InvoiceDocument


def aether_nav(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    return {
        "needs_audit_count": InvoiceDocument.objects.filter(
            uploaded_by=request.user,
            status=DocumentStatus.AUDIT_REQUIRED,
        ).count()
    }
