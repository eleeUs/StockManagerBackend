"""
Smoke tests for config/settings/production.py.

Not exercised anywhere else: pytest.ini's DJANGO_SETTINGS_MODULE is
config.settings.test (development-based), so nothing in the normal test
run ever imports production.py. These tests import it directly and
reload it between cases, since production.py's Sentry setup only runs
its `if SENTRY_DSN:` branch once per import and Python caches modules
in sys.modules — without the reload, the second test in a session would
just see the first test's already-executed module state.

Required env vars for config.settings.production (no defaults):
SECRET_KEY, DATABASE_URL, ALLOWED_HOSTS, CORS_ALLOWED_ORIGINS — set
explicitly via monkeypatch in every test here, rather than relying on
whatever a developer's local .env or CI's env happens to contain, so
these tests behave the same everywhere.

IMPORTANT: production.py does `from .base import *`. Reloading only
the `production` module does NOT re-execute `base`'s code — Python's
`from X import *` just re-reads names off the already-cached `base`
module object in sys.modules, which was fully executed once already
(at pytest session startup, when Django first loaded
config.settings.test -> development -> base). Without also reloading
`base`, `SECRET_KEY = env("SECRET_KEY")` never runs again, so deleting
the env var in a test has no effect and nothing raises. Both modules
must be reloaded, in dependency order (base, then production).
"""

import importlib

import pytest


def _set_required_env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-real-use")
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@localhost:5432/db")
    monkeypatch.setenv("ALLOWED_HOSTS", "example.com")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://example.com")


def _import_production_settings():
    import config.settings.base as base_settings
    import config.settings.production as production_settings

    # Order matters: production's `from .base import *` needs base's
    # module-level code to have already re-run with the current env.
    importlib.reload(base_settings)
    importlib.reload(production_settings)
    return production_settings


def test_production_settings_import_without_sentry_dsn(monkeypatch):
    """
    The common case for anyone spinning up a `production`-settings
    environment without Sentry configured (a fresh deploy target, a
    local smoke test) — must not raise, and must not require sentry-sdk
    to be installed at all, since SENTRY_DSN being empty means the
    `if SENTRY_DSN:` block in production.py never executes.
    """
    _set_required_env(monkeypatch)
    monkeypatch.delenv("SENTRY_DSN", raising=False)

    settings = _import_production_settings()

    assert settings.SENTRY_DSN == ""
    assert settings.DEBUG is False


def test_production_settings_import_with_sentry_dsn(monkeypatch):
    """
    With SENTRY_DSN set, production.py must import sentry_sdk and call
    init() without raising. Uses a syntactically valid but fake DSN —
    sentry_sdk.init() doesn't make a synchronous network call, so this
    doesn't require actual Sentry connectivity.
    """
    _set_required_env(monkeypatch)
    # Built via concatenation, not a literal "key@host" string: chat
    # tools and some editors treat a literal user@domain-looking
    # substring as an email address and silently rewrite/obfuscate it
    # on copy-paste — which is exactly what corrupted this line the
    # first time (the DSN below arrived on disk as the literal text
    # "[email protected]" instead of a real fake DSN, and
    # sentry_sdk failed to parse it as a URL — see chat history for
    # the traceback if this regresses).
    fake_dsn = "https://" + "faketestkey" + "@" + "o0.ingest.sentry.io" + "/1"
    monkeypatch.setenv("SENTRY_DSN", fake_dsn)
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "test")
    monkeypatch.setenv("SENTRY_RELEASE", "test-sha")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.5")

    settings = _import_production_settings()

    assert settings.SENTRY_DSN == fake_dsn
    # Confirms production.py actually took the `import sentry_sdk` branch,
    # not just that it read the env var correctly.
    assert hasattr(settings, "sentry_sdk")


def test_production_settings_requires_secret_key(monkeypatch):
    """
    SECRET_KEY has no default anywhere in the settings chain — confirms
    that stays true, since silently defaulting a secret key would be a
    much worse failure mode than an import-time crash.
    """
    _set_required_env(monkeypatch)
    monkeypatch.delenv("SECRET_KEY", raising=False)

    # base.py calls environ.Env.read_env(BASE_DIR / ".env") on every
    # reload, which re-reads the project's real .env file and calls
    # os.environ.setdefault() for each line in it. In any real dev
    # setup .env has a real SECRET_KEY, so setdefault() would silently
    # refill the value we just deleted before env("SECRET_KEY") ever
    # gets a chance to raise — defeating this test. Stub it to a no-op
    # so this test verifies "no SECRET_KEY anywhere", not "no
    # SECRET_KEY unless a .env file happens to provide one".
    import environ

    monkeypatch.setattr(environ.Env, "read_env", lambda *a, **kw: None)

    try:
        with pytest.raises(Exception):
            _import_production_settings()
    finally:
        # importlib.reload() executes in-place: a reload that raises
        # partway through can leave config.settings.base's cached module
        # object with a stale/missing SECRET_KEY attribute. monkeypatch
        # restores env vars automatically at teardown, but not module
        # state — so re-reload with a valid env here, leaving both
        # modules consistent for anything imported after this test.
        monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-real-use")
        _import_production_settings()
