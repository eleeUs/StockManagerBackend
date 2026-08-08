from pathlib import Path
from datetime import timedelta
import environ

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------
env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env("SECRET_KEY")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
]

LOCAL_APPS = [
    "apps.users",
    "apps.idempotency",
    "apps.audit",
    "apps.branches",
    "apps.products",
    "apps.suppliers",
    "apps.stock",
    "apps.movements",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # RequestIDMiddleware must be early so all subsequent middleware
    # and views have access to request.request_id
    "core.middleware.RequestIDMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # CorsMiddleware must sit before CommonMiddleware (django-cors-headers requirement)
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASES = {
    "default": env.db("DATABASE_URL")
    # Example: postgres://user:password@localhost:5432/stock_db
}

# ---------------------------------------------------------------------------
# Custom user model — must be defined before first migration
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "users.User"

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
# Primary hasher: Argon2id with explicitly configured parameters.
# See core/hashers.py for parameter rationale.
#
# PBKDF2 is kept as a fallback so that any passwords hashed before the
# Argon2 migration (e.g. during development) remain valid. Django detects
# which algorithm was used from the hash prefix and rehashes to Argon2 on
# the user's next successful login automatically.
PASSWORD_HASHERS = [
    "core.hashers.StockArgon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "core.exceptions.custom_exception_handler",
    # ---------------------------------------------------------------------------
    # Throttling
    # Global rates apply to all endpoints except those with explicit
    # throttle_classes (e.g. LoginView uses LoginRateThrottle at 5/min).
    # ---------------------------------------------------------------------------
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        # Unauthenticated requests to non-login endpoints (e.g. schema, health)
        "anon":  "20/minute",
        # Authenticated API usage — covers all business endpoints
        "user":  "200/minute",
        # Login attempts — per IP, applied only on LoginView
        # 5/min × 60min × 24h = 7,200 attempts/day max per IP
        # Combined with Argon2 (~100ms/attempt), brute-force is infeasible
        "login": "5/minute",
    },
}

# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=8),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    # Blacklist used tokens so logout actually invalidates them
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# ---------------------------------------------------------------------------
# API Documentation (drf-spectacular)
# ---------------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "Stock Management API",
    "DESCRIPTION": "Multi-branch stock management system",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ---------------------------------------------------------------------------
# CORS (django-cors-headers)
# Fail-safe default: no cross-origin requests allowed unless an environment
# explicitly opts in. development.py opens it up; production.py reads an
# explicit allow-list from the environment.
# ---------------------------------------------------------------------------
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = []

# ---------------------------------------------------------------------------
# Idempotency (apps/idempotency)
# Default True everywhere, including this default value. False is an
# operational escape hatch for emergencies (see docs/BUSINESS_RULES.md §12),
# not a supported steady state.
# ---------------------------------------------------------------------------
IDEMPOTENCY_KEY_REQUIRED = env.bool("IDEMPOTENCY_KEY_REQUIRED", default=True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        # Injects request_id into every log record produced during a request
        "request_id": {
            "()": "core.middleware.RequestIDFilter",
        },
    },
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} [req={request_id}] {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "filters": ["request_id"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}
