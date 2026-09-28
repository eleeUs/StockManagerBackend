"""
Settings for running the automated test suite.

Inherits from development.py (same DB, same DEBUG, same CORS-open
convenience) but strips out django-silk. Silk's SilkyMiddleware writes
a SilkRequest row plus a SQLQuery row for every query the app runs,
and SILKY_PYTHON_PROFILER adds further per-call profiling writes on
top of that. Running it during tests silently multiplies real query
counts several-fold, which makes django_assert_num_queries assertions
meaningless (see apps/movements/tests/test_query_count.py and
docs/phase-9-bugfix-plan.md §4), and its background write thread has
also been observed colliding with pytest-django's test-database
teardown ("database is being accessed by other users").

Never point pytest.ini at development.py directly — use this module.
"""

from .development import *  # noqa

MIDDLEWARE = [mw for mw in MIDDLEWARE if not mw.startswith("silk.")]  # noqa: F405
INSTALLED_APPS = [app for app in INSTALLED_APPS if app != "silk"]  # noqa: F405
SILKY_PYTHON_PROFILER = False
