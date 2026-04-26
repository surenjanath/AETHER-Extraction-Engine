import pytest
from django.test import Client
from rest_framework.test import APIRequestFactory

from documents.api.serializers import ExtractedDataSerializer
from documents.models import DocumentStatus, ExtractedData, InvoiceDocument
from documents.services.extraction import (
    _infer_document_type_from_text,
    _infer_invoice_number_from_text,
)


@pytest.mark.django_db
def test_live_api_includes_invoice_number_and_document_type(user):
    doc = InvoiceDocument.objects.create(
        uploaded_by=user,
        original_filename="x.png",
        status=DocumentStatus.AUDIT_REQUIRED,
    )
    ExtractedData.objects.create(
        document=doc,
        vendor_name="Acme",
        invoice_number="INV-77",
        document_type="invoice",
    )
    c = Client()
    assert c.login(username="tester", password="test-pass-123")
    resp = c.get(f"/api/documents/{doc.pk}/live/")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["extracted"]["invoice_number"] == "INV-77"
    assert payload["extracted"]["document_type"] == "invoice"


@pytest.mark.django_db
def test_extracted_data_serializer_has_new_fields(user):
    doc = InvoiceDocument.objects.create(
        uploaded_by=user,
        original_filename="x.png",
        status=DocumentStatus.VERIFIED,
    )
    ext = ExtractedData.objects.create(
        document=doc,
        vendor_name="Acme",
        invoice_number="INV-88",
        document_type="invoice",
    )
    request = APIRequestFactory().get("/")
    payload = ExtractedDataSerializer(ext, context={"request": request}).data
    assert payload["invoice_number"] == "INV-88"
    assert payload["document_type"] == "invoice"


def test_fallback_document_type_classifier():
    assert _infer_document_type_from_text("Invoice No 8891\nBill To XYZ\nDue Date 2026-04-30") == "invoice"
    assert _infer_document_type_from_text("Receipt\nCashier 2\nTender cash\nChange 1.00") == "receipt"
    assert _infer_document_type_from_text("random text with no useful markers") == "unknown"


def test_fallback_invoice_number_extractor():
    text = "Vendor ABC\nInvoice No: INV-2026-0099\nTotal: 123.45"
    assert _infer_invoice_number_from_text(text) == "INV-2026-0099"


def test_fallback_invoice_number_ignores_bill_to_lines():
    text = "BILL TO\nEast Repair Inc.\nINVOICE # US-001\nTOTAL 154.06"
    assert _infer_invoice_number_from_text(text) == "US-001"
