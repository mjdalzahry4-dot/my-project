"""Production settings. Configure every required value through the process environment."""

import os
from urllib.parse import unquote, urlsplit

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403

MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")


def _required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"{name} must be configured for production.")
    return value


def _env_bool(name, default="false"):
    value = os.environ.get(name, default).strip().lower()
    if value not in {"1", "0", "true", "false", "yes", "no"}:
        raise ImproperlyConfigured(f"{name} must be true or false.")
    return value in {"1", "true", "yes"}


SECRET_KEY = _required("DJANGO_SECRET_KEY")
if len(SECRET_KEY) < 50 or any(word in SECRET_KEY.lower() for word in ("replace", "changeme", "example", "development")):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a unique random production secret of at least 50 characters.")

DEBUG = False
ALLOWED_HOSTS = [host.strip() for host in _required("DJANGO_ALLOWED_HOSTS").split(",") if host.strip()]
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must contain explicit host names and cannot contain '*'.")

CORS_ALLOWED_ORIGINS = {
    origin.strip().rstrip("/").lower()
    for origin in os.environ.get("CORS_ORIGINS", os.environ.get("CORS_ALLOWED_ORIGINS", "")).split(",")
    if origin.strip()
}
for origin in CORS_ALLOWED_ORIGINS:
    parsed_origin = urlsplit(origin)
    if parsed_origin.scheme != "https" or not parsed_origin.netloc or parsed_origin.path or parsed_origin.query or parsed_origin.fragment:
        raise ImproperlyConfigured("Production CORS_ALLOWED_ORIGINS entries must be HTTPS origins without paths.")
CSRF_TRUSTED_ORIGINS = sorted(CORS_ALLOWED_ORIGINS)

database_url = os.environ.get("DATABASE_URL", "").strip()
if not database_url:
    # Keep the existing SQLite database in backend/db.sqlite3 unless an explicit
    # database URL is configured. Production startup never changes database engines.
    DATABASES["default"]["OPTIONS"] = {"timeout": 20}  # noqa: F405
else:
    parsed_database_url = urlsplit(database_url)
    if parsed_database_url.scheme == "sqlite":
        sqlite_path = unquote(parsed_database_url.path)
        if not sqlite_path or not sqlite_path.startswith("/") or parsed_database_url.netloc:
            raise ImproperlyConfigured("SQLite DATABASE_URL must contain an absolute local database path.")
        DATABASES["default"] = {  # noqa: F405
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": sqlite_path,
            "OPTIONS": {"timeout": 20},
        }
    elif parsed_database_url.scheme in {"postgres", "postgresql"} and parsed_database_url.hostname and parsed_database_url.path.strip("/"):
        if "replace" in (parsed_database_url.password or "").lower() or parsed_database_url.hostname.endswith(".invalid"):
            raise ImproperlyConfigured("Replace DATABASE_URL placeholders with the real database credentials and host in the secret store.")
        DATABASE_SSLMODE = os.environ.get("DATABASE_SSLMODE", "verify-full").strip().lower()
        if DATABASE_SSLMODE not in {"verify-full", "verify-ca"}:
            raise ImproperlyConfigured("PostgreSQL DATABASE_SSLMODE must be verify-full or verify-ca.")
        DATABASES["default"]["OPTIONS"]["sslmode"] = DATABASE_SSLMODE  # noqa: F405
        DATABASES["default"]["OPTIONS"]["connect_timeout"] = 5  # noqa: F405
        ssl_root_cert = os.environ.get("DATABASE_SSLROOTCERT", "").strip()
        if ssl_root_cert:
            DATABASES["default"]["OPTIONS"]["sslrootcert"] = ssl_root_cert  # noqa: F405
    else:
        raise ImproperlyConfigured("DATABASE_URL must be an absolute SQLite URL or a valid PostgreSQL URL.")

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if _env_bool("DJANGO_TRUST_PROXY_SSL_HEADER") else None
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS")
SECURE_HSTS_PRELOAD = _env_bool("DJANGO_SECURE_HSTS_PRELOAD")
if SECURE_HSTS_SECONDS < 0:
    raise ImproperlyConfigured("DJANGO_SECURE_HSTS_SECONDS cannot be negative.")
if SECURE_HSTS_PRELOAD and (not SECURE_HSTS_INCLUDE_SUBDOMAINS or SECURE_HSTS_SECONDS < 31536000):
    raise ImproperlyConfigured("HSTS preload requires subdomain coverage and at least one year of HTTPS-only operation.")

STATIC_URL = "/static/"
STATICFILES_DIRS = [PROJECT_ROOT / "frontend"]
WHITENOISE_ROOT = PROJECT_ROOT / "frontend"
WHITENOISE_INDEX_FILE = True

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"},
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "production": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "production"},
    },
    "root": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO").upper()},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
