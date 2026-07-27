from .base import *  # noqa

DEBUG = True

ALLOWED_HOSTS = ["*"]

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
