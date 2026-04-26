from django.urls import path

from documents import views

app_name = "documents"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("upload/", views.BulkUploadView.as_view(), name="bulk_upload"),
    path("audit/", views.AuditQueueView.as_view(), name="audit_queue"),
    path(
        "audit/bulk-verify/",
        views.BulkVerifyAuditView.as_view(),
        name="bulk_verify_audit",
    ),
    path(
        "audit/bulk-action/",
        views.BulkAuditActionView.as_view(),
        name="bulk_audit_action",
    ),
    path("review/<int:pk>/", views.DocumentReviewView.as_view(), name="review"),
    path(
        "activity/<int:pk>/",
        views.DocumentActivityView.as_view(),
        name="document_activity",
    ),
    path("history/", views.HistoryView.as_view(), name="history"),
    path(
        "extraction-logs/",
        views.ExtractionLogListView.as_view(),
        name="extraction_logs",
    ),
    path(
        "ai-logs/",
        views.AIRuntimeLogView.as_view(),
        name="ai_runtime_logs",
    ),
    path("categories/", views.CategoriesView.as_view(), name="categories"),
    path("export/", views.ExportView.as_view(), name="export"),
    path("reports/", views.ReportView.as_view(), name="reports"),
    path("settings/", views.SettingsView.as_view(), name="settings"),
]
