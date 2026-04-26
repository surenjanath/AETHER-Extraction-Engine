from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from documents.models import Category, DocumentStatus, ExtractedData, InvoiceDocument, LineItem


@pytest.mark.django_db
def test_review_post_marks_verified_with_force(user):
    cat, _ = Category.objects.get_or_create(
        name="Office / Supplies",
        defaults={"description": "", "is_system_generated": False},
    )
    doc = InvoiceDocument.objects.create(
        uploaded_by=user,
        original_filename="x.png",
        status=DocumentStatus.AUDIT_REQUIRED,
    )
    ext = ExtractedData.objects.create(
        document=doc,
        vendor_name="Acme",
        subtotal=Decimal("1.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("9.00"),
        category=cat,
    )
    LineItem.objects.create(
        extracted=ext,
        description="Line",
        line_total=Decimal("1.00"),
        ordering=0,
    )

    client = Client()
    assert client.login(username="tester", password="test-pass-123")
    url = reverse("documents:review", args=[doc.pk])
    data = {
        "ext-vendor_name": "Acme",
        "ext-date_issued": "",
        "ext-invoice_number": "INV-1001",
        "ext-document_type": "invoice",
        "ext-subtotal": "1.00",
        "ext-tax_amount": "0.00",
        "ext-total_amount": "9.00",
        "ext-category": str(cat.pk),
        "ext-force_verify": "on",
        "lines-TOTAL_FORMS": "1",
        "lines-INITIAL_FORMS": "1",
        "lines-MIN_NUM_FORMS": "0",
        "lines-MAX_NUM_FORMS": "1000",
        "lines-0-id": str(ext.line_items.first().pk),
        "lines-0-description": "Line",
        "lines-0-quantity": "1",
        "lines-0-unit_price": "",
        "lines-0-line_total": "1.00",
        "lines-0-ordering": "0",
        "lines-0-DELETE": "",
    }
    r = client.post(url, data)
    assert r.status_code == 302
    doc.refresh_from_db()
    assert doc.status == DocumentStatus.VERIFIED
