import pytest
from pydantic import ValidationError

from documents.services.schema import ExtractionSchema


def test_extraction_schema_accepts_line_items():
    payload = {
        "vendor_name": "X",
        "date_issued": "2024-01-15",
        "subtotal": 10,
        "tax_amount": 1,
        "total_amount": 11,
        "line_items": [{"description": "A", "line_total": 10}],
    }
    obj = ExtractionSchema.model_validate(payload)
    assert obj.vendor_name == "X"
    assert len(obj.line_items) == 1


def test_extraction_schema_rejects_bad_json_shape():
    with pytest.raises(ValidationError):
        ExtractionSchema.model_validate({"line_items": "nope"})


def test_extraction_schema_tolerates_null_vendor_and_quantity():
    payload = {
        "vendor_name": None,
        "date_issued": None,
        "subtotal": 10,
        "tax_amount": 1,
        "total_amount": 11,
        "line_items": [{"description": "A", "quantity": None, "line_total": 10}],
    }
    obj = ExtractionSchema.model_validate(payload)
    assert obj.vendor_name == ""
    assert obj.line_items[0].quantity == 1


def test_extraction_schema_rejects_date_like_vendor_name():
    payload = {
        "vendor_name": "DATE 06/01/2016 WED",
        "date_issued": "2016-06-01",
        "subtotal": 24.20,
        "tax_amount": None,
        "total_amount": 24.20,
        "line_items": [{"description": "A", "line_total": 24.20}],
    }
    obj = ExtractionSchema.model_validate(payload)
    assert obj.vendor_name == ""


def test_extraction_schema_normalizes_document_type_and_invoice_number():
    payload = {
        "vendor_name": "X",
        "date_issued": None,
        "invoice_number": "   INV-42   ",
        "document_type": "INVOICE",
        "subtotal": 10,
        "tax_amount": 1,
        "total_amount": 11,
        "line_items": [],
    }
    obj = ExtractionSchema.model_validate(payload)
    assert obj.invoice_number == "INV-42"
    assert obj.document_type == "invoice"


def test_extraction_schema_drops_junk_invoice_number():
    payload = {
        "vendor_name": "X",
        "date_issued": None,
        "invoice_number": "@" * 200,
        "document_type": "weird-value",
        "subtotal": 10,
        "tax_amount": 1,
        "total_amount": 11,
        "line_items": [],
    }
    obj = ExtractionSchema.model_validate(payload)
    assert obj.invoice_number is None
    assert obj.document_type == "unknown"
