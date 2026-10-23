import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import OneTimeToken


def issue_token(user, purpose, lifetime=timedelta(hours=1)):
    """Return a bearer secret once while storing only its SHA-256 digest."""
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    OneTimeToken.objects.create(user=user, purpose=purpose, token_hash=digest, expires_at=timezone.now() + lifetime)
    return raw


@transaction.atomic
def get_valid_token(raw, purpose):
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    token = OneTimeToken.objects.select_for_update().filter(token_hash=digest, purpose=purpose, used_at__isnull=True).first()
    if not token or token.expires_at <= timezone.now():
        return None
    return token


def consume_token(token):
    token.used_at = timezone.now()
    token.save(update_fields=["used_at"])
