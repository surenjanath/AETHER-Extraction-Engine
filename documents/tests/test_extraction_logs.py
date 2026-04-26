from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.urls import reverse

from documents.models import ExtractionLog, InvoiceDocument
from documents.services.extraction_logging import append_extraction_log

User = get_user_model()


def _invoice(user, name: str = "a.pdf") -> InvoiceDocument:
    doc = InvoiceDocument(uploaded_by=user, original_filename=name)
    doc.file.save(name, ContentFile(b"%PDF-1.4 test"), save=True)
    return doc


@pytest.mark.django_db
def test_append_extraction_log_creates_row():
    user = User.objects.create_user(username="u1", password="x")
    doc = _invoice(user)
    append_extraction_log(
        doc.pk,
        "info",
        "hello",
        event="test_event",
        details={"k": 1},
    )
    log = ExtractionLog.objects.get(document=doc)
    assert log.message == "hello"
    assert log.event == "test_event"
    assert log.details == {"k": 1}


@pytest.mark.django_db
def test_extraction_logs_list_scoped_to_user(client):
    u1 = User.objects.create_user(username="a", password="pw")
    u2 = User.objects.create_user(username="b", password="pw")
    d1 = _invoice(u1, "1.pdf")
    d2 = _invoice(u2, "2.pdf")
    append_extraction_log(d1.pk, "info", "mine", event="e1")
    append_extraction_log(d2.pk, "info", "theirs", event="e2")

    client.force_login(u1)
    url = reverse("documents:extraction_logs")
    resp = client.get(url)
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "mine" in content
    assert "theirs" not in content

    resp2 = client.get(url, {"document": str(d2.pk)})
    assert resp2.status_code == 200
    assert "theirs" not in resp2.content.decode()
