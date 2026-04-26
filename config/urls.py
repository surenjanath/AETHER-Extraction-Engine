from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from documents.views import AppLoginView, AppLogoutView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("documents.api.urls")),
    path("accounts/login/", AppLoginView.as_view(), name="login"),
    path("accounts/logout/", AppLogoutView.as_view(), name="logout"),
    path("app/", include("documents.urls")),
    path("", RedirectView.as_view(pattern_name="documents:dashboard", permanent=False)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
