from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from documents.models import (
    ApiKey,
    DocumentStatus,
    ExtractedData,
    InvoiceDocument,
)


@pytest.mark.django_db
def test_bulk_action_mark_duplicate(user):
    doc1 = InvoiceDocument.objects.create(
        uploaded_by=user,
        original_filename="a.png",
        status=DocumentStatus.AUDIT_REQUIRED,
    )
    doc2 = InvoiceDocument.objects.create(
        uploaded_by=user,
        original_filename="b.png",
        status=DocumentStatus.AUDIT_REQUIRED,
    )
    c = Client()
    assert c.login(username="tester", password="test-pass-123")
    r = c.post(
        reverse("documents:bulk_audit_action"),
        {"doc_ids": str(doc2.pk), "action": "mark_duplicate"},
    )
    assert r.status_code == 302
    doc2.refresh_from_db()
    assert doc2.is_duplicate is True


@pytest.mark.django_db
def test_mark_duplicate_api(user):
    doc1 = InvoiceDocument.objects.create(uploaded_by=user, original_filename="x.png")
    doc2 = InvoiceDocument.objects.create(uploaded_by=user, original_filename="y.png")
    client = APIClient()
    client.force_authenticate(user=user)
    r = client.post(f"/api/documents/{doc2.pk}/mark-duplicate/", {"canonical_id": doc1.pk}, format="json")
    assert r.status_code == 200
    doc2.refresh_from_db()
    assert doc2.canonical_document_id == doc1.pk


@pytest.mark.django_db
def test_export_preset_saved(user):
    client = Client()
    assert client.login(username="tester", password="test-pass-123")
    r = client.post(
        reverse("documents:export"),
        {
            "date_from": "2026-01-01",
            "date_to": "2026-01-31",
            "export_format": "csv",
            "preset_name": "JanClose",
        },
    )
    assert r.status_code == 200
    assert user.export_presets.filter(name="JanClose").exists()


@pytest.mark.django_db
def test_api_key_auth_for_queue_stats(user):
    raw = ApiKey.build_raw_key()
    ApiKey.objects.create(
        name="Test",
        key_prefix=raw[:12],
        key_hash=ApiKey.hash_key(raw),
        created_by=user,
        scopes=["documents:read"],
    )
    client = APIClient()
    r = client.get(
        "/api/queue-stats/",
        HTTP_AUTHORIZATION=f"ApiKey {raw}",
    )
    assert r.status_code == 200

