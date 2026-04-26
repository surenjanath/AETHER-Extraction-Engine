from django.urls import include, path
from rest_framework.routers import DefaultRouter

from documents.api import views

router = DefaultRouter()
router.register("documents", views.InvoiceDocumentViewSet, basename="invoice")

urlpatterns = [
    path("", include(router.urls)),
    path("health/ollama/", views.health_ollama, name="health-ollama"),
    path("ollama/tags/", views.ollama_tags_list, name="ollama-tags"),
    path("ollama/prepare-model/", views.ollama_prepare_model, name="ollama-prepare-model"),
    path("queue-stats/", views.queue_stats, name="queue-stats"),
    path("api-keys/", views.api_keys_list, name="api-keys-list"),
    path("webhooks/test-send/", views.webhook_test_send, name="webhook-test-send"),
    path("export/", views.export_csv, name="export-csv"),
    path("export.xlsx/", views.export_xlsx, name="export-xlsx"),
]
