from __future__ import annotations

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import authentication

from documents.models import ApiKey


class ApiKeyAuthentication(authentication.BaseAuthentication):
    keyword = "ApiKey"

    def authenticate(self, request):
        auth = request.headers.get("Authorization", "")
        if not auth or not auth.startswith(f"{self.keyword} "):
            return None
        raw = auth[len(self.keyword) + 1 :].strip()
        if not raw:
            return None
        digest = ApiKey.hash_key(raw)
        key = ApiKey.objects.filter(is_active=True, key_hash=digest).select_related("created_by").first()
        if not key:
            return None
        key.last_used_at = timezone.now()
        key.save(update_fields=["last_used_at"])
        return (key.created_by, key)

