from decimal import Decimal

import pytest

from documents.models import Category, DocumentStatus, ExtractedData, InvoiceDocument, LineItem
from documents.services.audit import run_deterministic_audit


@pytest.mark.django_db
def test_audit_all_ok(user):
    cat = Category.objects.create(name="Test Cat", is_system_generated=False)
    doc = InvoiceDocument.objects.create(
        uploaded_by=user,
        original_filename="a.png",
        status=DocumentStatus.PENDING_EXTRACTION,
    )
    ext = ExtractedData.objects.create(
        document=doc,
        vendor_name="Acme",
        subtotal=Decimal("10.00"),
        tax_amount=Decimal("1.00"),
        total_amount=Decimal("11.00"),
        category=cat,
    )
    LineItem.objects.create(
        extracted=ext,
        description="Item",
        line_total=Decimal("10.00"),
        ordering=0,
    )
    ext = ExtractedData.objects.prefetch_related("line_items").get(pk=ext.pk)
    audit = run_deterministic_audit(ext)
    assert audit["all_ok"]


@pytest.mark.django_db
def test_audit_tax_mismatch(user):
    doc = InvoiceDocument.objects.create(
        uploaded_by=user,
        original_filename="b.png",
        status=DocumentStatus.PENDING_EXTRACTION,
    )
    ext = ExtractedData.objects.create(
        document=doc,
        vendor_name="Acme",
        subtotal=Decimal("10.00"),
        tax_amount=Decimal("1.00"),
        total_amount=Decimal("99.00"),
    )
    LineItem.objects.create(
        extracted=ext,
        description="Item",
        line_total=Decimal("10.00"),
        ordering=0,
    )
    ext = ExtractedData.objects.prefetch_related("line_items").get(pk=ext.pk)
    audit = run_deterministic_audit(ext)
    assert not audit["tax_total_ok"]
