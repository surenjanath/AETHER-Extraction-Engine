"""Routing: OCR-tuned vision models (e.g. glm-ocr) must not receive structured JSON vision prompts."""

from __future__ import annotations

from documents.services.extraction import _model_name_is_ocr_tuned


def test_model_name_is_ocr_tuned_glm():
    assert _model_name_is_ocr_tuned("glm-ocr:latest") is True
    assert _model_name_is_ocr_tuned("GLM-OCR") is True


def test_model_name_is_ocr_tuned_general_vision_false():
    assert _model_name_is_ocr_tuned("llava:latest") is False
    assert _model_name_is_ocr_tuned("qwen2.5vl:latest") is False
    assert _model_name_is_ocr_tuned("") is False
