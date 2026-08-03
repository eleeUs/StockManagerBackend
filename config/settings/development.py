from .base import *  # noqa

DEBUG = True

ALLOWED_HOSTS = ["*"]

# ---------------------------------------------------------------------------
# CORS: fully open in development for local frontend work
# ---------------------------------------------------------------------------
CORS_ALLOW_ALL_ORIGINS = True

# ---------------------------------------------------------------------------
# django-silk: query profiling in development
# ---------------------------------------------------------------------------
INSTALLED_APPS += ["silk"]  # noqa: F405
MIDDLEWARE += ["silk.middleware.SilkyMiddleware"]  # noqa: F405

SILKY_PYTHON_PROFILER = True

# ---------------------------------------------------------------------------
# django-extensions
# ---------------------------------------------------------------------------
INSTALLED_APPS += ["django_extensions"]  # noqa: F405
