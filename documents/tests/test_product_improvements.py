from decimal import Decimal
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from documents.models import (
    Category,
    DocumentStatus,
    ExtractedData,
    InvoiceDocument,
    LineItem,
    SystemSettings,
)


@pytest.mark.django_db
def test_health_ollama_requires_auth():
    r = APIClient().get("/api/health/ollama/")
    assert r.status_code == 403


@pytest.mark.django_db
@patch(
    "documents.api.views.check_ollama_tags",
    return_value={
        "ok": True,
        "status_code": 200,
        "error": None,
        "models_sample": ["llama3:latest"],
        "checked_at": "2026-01-01T00:00:00+00:00",
    },
)
def test_health_ollama_authenticated(_mock, user):
    client = APIClient()
    client.force_authenticate(user=user)
    r = client.get("/api/health/ollama/")
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.django_db
@patch("documents.api.views.async_task")
def test_requeue_pending(mock_task, user):
    doc = InvoiceDocument.objects.create(
        uploaded_by=user,
        original_filename="a.png",
        status=DocumentStatus.PENDING_EXTRACTION,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    r = client.post(f"/api/documents/{doc.pk}/requeue/")
    assert r.status_code == 200
    mock_task.assert_called_once_with(
        "documents.tasks.extract_invoice_document",
        doc.pk,
    )


@pytest.mark.django_db
def test_requeue_verified_rejected(user):
    doc = InvoiceDocument.objects.create(
        uploaded_by=user,
        original_filename="a.png",
        status=DocumentStatus.VERIFIED,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    r = client.post(f"/api/documents/{doc.pk}/requeue/")
    assert r.status_code == 400


@pytest.mark.django_db
def test_bulk_verify_only_math_clean(user):
    cat = Category.objects.create(name="Cat", is_system_generated=False)
    good = InvoiceDocument.objects.create(
        uploaded_by=user,
        original_filename="good.png",
        status=DocumentStatus.AUDIT_REQUIRED,
    )
    ext_ok = ExtractedData.objects.create(
        document=good,
        vendor_name="A",
        subtotal=Decimal("10.00"),
        tax_amount=Decimal("1.00"),
        total_amount=Decimal("11.00"),
        category=cat,
    )
    LineItem.objects.create(
        extracted=ext_ok,
        description="L",
        line_total=Decimal("10.00"),
        ordering=0,
    )

    bad = InvoiceDocument.objects.create(
        uploaded_by=user,
        original_filename="bad.png",
        status=DocumentStatus.AUDIT_REQUIRED,
    )
    ext_bad = ExtractedData.objects.create(
        document=bad,
        vendor_name="B",
        subtotal=Decimal("10.00"),
        tax_amount=Decimal("1.00"),
        total_amount=Decimal("99.00"),
        category=cat,
    )
    LineItem.objects.create(
        extracted=ext_bad,
        description="L",
        line_total=Decimal("10.00"),
        ordering=0,
    )

    client = Client(enforce_csrf_checks=False)
    assert client.login(username="tester", password="test-pass-123")
    url = reverse("documents:bulk_verify_audit")
    r = client.post(url, {"doc_id": [str(good.pk), str(bad.pk)]})
    assert r.status_code == 302
    good.refresh_from_db()
    bad.refresh_from_db()
    assert good.status == DocumentStatus.VERIFIED
    assert bad.status == DocumentStatus.AUDIT_REQUIRED


@pytest.mark.django_db
def test_document_activity_page(user):
    doc = InvoiceDocument.objects.create(
        uploaded_by=user,
        original_filename="z.png",
        status=DocumentStatus.VERIFIED,
    )
    client = Client()
    assert client.login(username="tester", password="test-pass-123")
    r = client.get(reverse("documents:document_activity", args=[doc.pk]))
    assert r.status_code == 200


@pytest.mark.django_db
def test_category_approve_system(user):
    cat = Category.objects.create(
        name="SysCat",
        description="",
        is_system_generated=True,
    )
    c = Client(enforce_csrf_checks=False)
    assert c.login(username="tester", password="test-pass-123")
    r2 = c.post(reverse("documents:categories"), {"approve_category": str(cat.pk)})
    assert r2.status_code == 302
    cat.refresh_from_db()
    assert cat.is_system_generated is False


@pytest.mark.django_db
def test_reports_page_includes_chart(user):
    client = Client()
    assert client.login(username="tester", password="test-pass-123")
    r = client.get(reverse("documents:reports"))
    assert r.status_code == 200


@pytest.mark.django_db
def test_ollama_tags_requires_auth():
    assert APIClient().get("/api/ollama/tags/").status_code == 403


@pytest.mark.django_db
@patch("documents.api.views.ollama_tags_full", return_value=[{"name": "a:latest"}])
def test_ollama_tags_authenticated(_mock, user):
    client = APIClient()
    client.force_authenticate(user=user)
    r = client.get("/api/ollama/tags/")
    assert r.status_code == 200
    assert r.json()["models"][0]["name"] == "a:latest"


@pytest.mark.django_db
@patch("documents.api.views.refresh_capabilities_after_save")
@patch(
    "documents.api.views.ollama_show",
    return_value={"capabilities": ["vision", "completion"]},
)
@patch("documents.api.views.ollama_pull_sync", return_value=(True, "success"))
def test_prepare_model_vision_updates_row(
    _mock_pull, _mock_show, mock_refresh, user
):
    SystemSettings.objects.update_or_create(
        pk=1,
        defaults={"ollama_base_url": "http://127.0.0.1:11434"},
    )
    client = APIClient()
    client.force_authenticate(user=user)
    r = client.post(
        "/api/ollama/prepare-model/",
        {"role": "vision", "name": "custom:tag", "pull": False},
        format="json",
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["has_vision"] is True
    s = SystemSettings.objects.get(pk=1)
    assert s.ollama_vision_model == "custom:tag"
    mock_refresh.assert_called()
