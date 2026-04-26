"""Regression tests using repo-root ``image.png`` (receipt-style sample)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from documents.services.ollama_client import extract_with_retries
from documents.services.text_extract import vision_png_size_candidates


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _image_png_bytes() -> bytes:
    path = _repo_root() / "image.png"
    if not path.is_file():
        pytest.skip(f"missing fixture image: {path}")
    return path.read_bytes()


def test_image_png_is_valid_png_and_vision_candidates():
    raw = _image_png_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "fixture must be PNG"

    variants = vision_png_size_candidates(raw)
    assert len(variants) >= 1
    assert variants[0] == raw

    # Each variant is a PNG; sizes (bytes) should not grow when adding downscales
    prev_len = len(variants[0]) + 1
    for i, v in enumerate(variants):
        assert v[:8] == b"\x89PNG\r\n\x1a\n", f"variant {i} must stay PNG"
        assert len(v) <= prev_len
        prev_len = len(v)


@patch("documents.services.ollama_client.call_ollama_generate")
def test_image_png_extract_with_retries_succeeds_with_mocked_ollama(mock_generate):
    """Full vision path: real ``image.png`` bytes → b64 → schema parse (Ollama mocked)."""
    raw = _image_png_bytes()
    payload = {
        "vendor_name": "Mock Vendor",
        "date_issued": "2026-04-01",
        "subtotal": 10.0,
        "tax_amount": 1.0,
        "total_amount": 11.0,
        "line_items": [
            {"description": "Item A", "quantity": 1, "unit_price": 10.0, "line_total": 10.0}
        ],
    }
    mock_generate.return_value = json.dumps(payload)

    parsed, raw_response, errors = extract_with_retries(
        prompt="Extract receipt fields from the image.",
        model="mock:vision",
        image_bytes=raw,
        max_attempts=2,
        base_url="http://127.0.0.1:11434",
    )

    assert parsed.vendor_name == "Mock Vendor"
    assert parsed.total_amount is not None
    assert float(parsed.total_amount) == 11.0
    assert errors == []
    assert "Mock Vendor" in raw_response
    assert mock_generate.called
    # First call should use largest vision candidate (full image or first shrink tier)
    first_kw = mock_generate.call_args_list[0].kwargs
    assert first_kw.get("images_b64") is not None
    assert len(first_kw["images_b64"]) == 1
    assert len(first_kw["images_b64"][0]) > 100
