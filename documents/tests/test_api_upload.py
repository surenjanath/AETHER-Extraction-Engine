from io import BytesIO
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from documents.models import DocumentStatus, InvoiceDocument


@pytest.mark.django_db
def test_queue_stats_requires_login():
    client = APIClient()
    r = client.get("/api/queue-stats/")
    assert r.status_code == 403


@pytest.mark.django_db
def test_queue_stats_authenticated(user):
    client = APIClient()
    client.force_authenticate(user=user)
    r = client.get("/api/queue-stats/")
    assert r.status_code == 200
    assert r.json()["verified"] == 0


@pytest.mark.django_db
@patch("documents.api.views.async_task")
def test_create_document_enqueues_extraction(mock_async, user):
    client = APIClient()
    client.force_authenticate(user=user)
    upload = SimpleUploadedFile("receipt.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
    r = client.post("/api/documents/", {"file": upload}, format="multipart")
    assert r.status_code == 201
    doc = InvoiceDocument.objects.get(uploaded_by=user)
    assert doc.status == DocumentStatus.PENDING_EXTRACTION
    mock_async.assert_called_once_with(
        "documents.tasks.extract_invoice_document",
        doc.pk,
    )
