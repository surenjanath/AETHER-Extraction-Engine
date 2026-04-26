"""Ollama plain-text OCR (replaces Tesseract)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from documents.services.ollama_client import (
    OCR_PLAIN_PROMPT,
    _parse_json_object,
    ocr_image_with_ollama,
)
from documents.services.extraction import _cleanup_line_items, _infer_date_from_text
from documents.services.schema import ExtractionSchema
from documents.services.text_extract import ocr_image_bytes


def _one_pixel_png() -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(240, 240, 240)).save(buf, format="PNG")
    return buf.getvalue()


def test_ocr_image_with_ollama_returns_transcription():
    png = _one_pixel_png()
    with patch("documents.services.ollama_client.call_ollama_generate") as m:
        m.return_value = "Walmart\nTotal 10.00"
        out = ocr_image_with_ollama(
            png, model="llava:latest", base_url="http://127.0.0.1:11434"
        )
    assert out == "Walmart\nTotal 10.00"
    m.assert_called_once()
    assert m.call_args.args[0] == "llava:latest"
    assert OCR_PLAIN_PROMPT in m.call_args.args[1]


def test_ocr_image_bytes_skips_when_not_vision_capable():
    assert (
        ocr_image_bytes(
            b"x",
            ollama_model="m",
            ollama_base_url="http://127.0.0.1:11434",
            vision_capable=False,
        )
        == ""
    )


@patch("documents.services.ollama_client.ocr_image_with_ollama", return_value="ok")
def test_ocr_image_bytes_skip_gate_runs_without_vision_flag(_m):
    assert (
        ocr_image_bytes(
            b"x",
            ollama_model="glm-ocr:latest",
            ollama_base_url="http://127.0.0.1:11434",
            vision_capable=False,
            skip_capability_gate=True,
        )
        == "ok"
    )


def test_parse_json_object_accepts_chatter_and_json5_relaxed():
    raw = (
        "Here is the extraction:\n"
        "{ 'vendor_name': 'Walmart', 'date_issued': null, "
        "'subtotal': 25.53, 'tax_amount': 1.65, 'total_amount': 27.18, "
        "'line_items': [] }\nThanks."
    )
    obj = _parse_json_object(raw)
    assert obj["vendor_name"] == "Walmart"
    assert float(obj["total_amount"]) == 27.18


@patch("documents.services.ollama_client.call_ollama_generate", return_value="")
def test_ocr_image_bytes_returns_empty_when_model_empty(_m):
    assert (
        ocr_image_bytes(
            _one_pixel_png(),
            ollama_model="llava:latest",
            ollama_base_url="http://127.0.0.1:11434",
        )
        == ""
    )


def test_infer_date_from_text_prefers_labeled_date():
    text = "Circle K\nDate: 2/18/2019   Time: 10:09:02 AM\nTotal 20.00"
    out = _infer_date_from_text(text)
    assert out is not None
    assert out.isoformat() == "2019-02-18"


def test_cleanup_line_items_drops_noisy_rows_when_drift_high():
    parsed = ExtractionSchema.model_validate(
        {
            "vendor_name": "Circle K",
            "date_issued": "2019-02-18",
            "subtotal": 19.39,
            "tax_amount": 0.61,
            "total_amount": 20.00,
            "line_items": [
                {"description": "A", "quantity": 1, "unit_price": 1, "line_total": 1.99},
                {"description": "B", "quantity": 1, "unit_price": 1, "line_total": 2.19},
                {"description": "C", "quantity": 1, "unit_price": 1, "line_total": 3.99},
                {"description": "D", "quantity": 1, "unit_price": 1, "line_total": 4.99},
                {"description": "E", "quantity": 1, "unit_price": 1, "line_total": 5.99},
                {"description": "F", "quantity": 1, "unit_price": 1, "line_total": 6.99},
                {"description": "G", "quantity": 1, "unit_price": 1, "line_total": 7.99},
                {"description": "H", "quantity": 1, "unit_price": 1, "line_total": 8.99},
            ],
        }
    )
    _cleanup_line_items(parsed)
    assert parsed.line_items == []
