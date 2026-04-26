from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from documents.models import Category, DocumentStatus, ExtractedData, ExtractionLog, InvoiceDocument, SystemSettings
from documents.services.crew_pipeline import run_crewai_pipeline
from documents.services.schema import ExtractionSchema


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (16, 16), color=(250, 250, 250)).save(buf, format="PNG")
    return buf.getvalue()


def _make_doc(user) -> InvoiceDocument:
    return InvoiceDocument.objects.create(
        uploaded_by=user,
        original_filename="receipt.png",
        file=SimpleUploadedFile("receipt.png", _png_bytes(), content_type="image/png"),
    )


def _parsed_payload() -> ExtractionSchema:
    return ExtractionSchema.model_validate(
        {
            "vendor_name": "Test Vendor",
            "date_issued": "2026-04-25",
            "subtotal": 10.00,
            "tax_amount": 1.00,
            "total_amount": 11.00,
            "line_items": [
                {"description": "Item", "quantity": 1, "unit_price": 10.00, "line_total": 10.00}
            ],
        }
    )


class CrewAIRescanTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="u-test", password="pw")
        self.category = Category.objects.create(name="General", is_system_generated=False)

    def _configure_runtime(self):
        SystemSettings.objects.update_or_create(
            pk=1,
            defaults={
                "max_document_rescan_attempts": 1,  # total attempts = 2
                "rescan_backoff_seconds": 0,
                "use_vision_extraction": False,
            },
        )

    def test_crewai_pipeline_rescan_retries_then_verifies(self):
        doc = _make_doc(self.user)
        self._configure_runtime()
        audits = iter(
            [
                {"all_ok": False, "messages": ["retry please"]},
                {"all_ok": True, "messages": []},
            ]
        )
        with (
            patch("documents.services.crew_pipeline.extract_with_retries", return_value=(_parsed_payload(), "{}", [])),
            patch("documents.services.crew_pipeline.ocr_image_bytes", return_value="vendor total 11.00"),
            patch("documents.services.crew_pipeline._cleanup_line_items", return_value=None),
            patch("documents.services.crew_pipeline._infer_date_from_text", return_value=date(2026, 4, 25)),
            patch("documents.services.crew_pipeline.assign_category", return_value=(self.category, "ok")),
            patch("documents.services.crew_pipeline.heuristic_confidence", return_value=0.91),
            patch("documents.services.crew_pipeline.run_deterministic_audit", side_effect=lambda extracted: next(audits)),
        ):
            run_crewai_pipeline(doc.pk)

        doc.refresh_from_db()
        self.assertEqual(doc.status, DocumentStatus.VERIFIED)
        self.assertEqual(doc.extraction_attempts, 2)
        self.assertEqual(doc.last_rescan_reason, "")
        self.assertEqual(ExtractionLog.objects.filter(document=doc, event="rescan_attempt_started").count(), 2)

    def test_crewai_pipeline_rescan_reaches_max_and_stays_audit_required(self):
        doc = _make_doc(self.user)
        self._configure_runtime()
        with (
            patch("documents.services.crew_pipeline.extract_with_retries", return_value=(_parsed_payload(), "{}", [])),
            patch("documents.services.crew_pipeline.ocr_image_bytes", return_value="vendor total 11.00"),
            patch("documents.services.crew_pipeline._cleanup_line_items", return_value=None),
            patch("documents.services.crew_pipeline._infer_date_from_text", return_value=date(2026, 4, 25)),
            patch("documents.services.crew_pipeline.assign_category", return_value=(self.category, "ok")),
            patch("documents.services.crew_pipeline.heuristic_confidence", return_value=0.42),
            patch(
                "documents.services.crew_pipeline.run_deterministic_audit",
                return_value={"all_ok": False, "messages": ["still failing"]},
            ),
        ):
            run_crewai_pipeline(doc.pk)

        doc.refresh_from_db()
        self.assertEqual(doc.status, DocumentStatus.AUDIT_REQUIRED)
        self.assertEqual(doc.extraction_attempts, 2)
        self.assertEqual(doc.last_rescan_reason, "deterministic_audit_failed")
        self.assertTrue(ExtractionLog.objects.filter(document=doc, event="rescan_max_reached").exists())

    def test_history_shows_verified_view_receipt_action(self):
        self.client.force_login(self.user)
        doc = _make_doc(self.user)
        doc.status = DocumentStatus.VERIFIED
        doc.save(update_fields=["status"])
        ExtractedData.objects.create(
            document=doc,
            vendor_name="Verified Vendor",
            subtotal=Decimal("10.00"),
            tax_amount=Decimal("1.00"),
            total_amount=Decimal("11.00"),
        )

        response = self.client.get(reverse("documents:history"))
        content = response.content.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn("View receipt", content)
        self.assertIn(reverse("documents:review", args=[doc.pk]), content)
