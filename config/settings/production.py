from .base import *  # noqa

# Explicit (non-star) import of the one name this file mutates rather
# than just reads/overrides — makes DATABASES an unambiguous reference
# for ruff (F405) and for readers, instead of relying on the star
# import above to have brought it in.
from .base import DATABASES  # noqa: F401
import environ

env = environ.Env()

DEBUG = False

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

# ---------------------------------------------------------------------------
# Database: in production, DATABASE_URL (read by base.py into DATABASES
# via env.db()) points at PgBouncer (pool_mode = transaction), not at
# Postgres directly — see docker-compose.prod.yml and
# docs/infra/pgbouncer.md. The two settings below are consequences of
# that, not independent tuning knobs:
# ---------------------------------------------------------------------------

# PgBouncer already pools the server-side (PgBouncer→Postgres)
# connections; Django holding its own long-lived (Django→PgBouncer)
# connections on top of that would just move the connection-count
# problem up one hop instead of solving it. CONN_MAX_AGE=0 closes the
# Django-side connection at the end of every request, which is cheap
# because it's only closing a connection to PgBouncer (in the same
# Docker network), not doing a fresh TLS/auth handshake against
# Postgres itself.
#
# CONN_HEALTH_CHECKS is deliberately NOT set here: it pings the
# connection before reuse, which has no effect when CONN_MAX_AGE=0
# closes that connection every request anyway. Only add it back if
# CONN_MAX_AGE is raised above 0 — re-tune together, informed by
# Equipo D's load test, not before.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=0)

# Required with pool_mode = transaction: in transaction pooling, a
# server-side connection can be handed to a *different* client as soon
# as the current transaction ends. A named server-side cursor
# (Queryset.iterator(), values_list(... ).iterator()) opened on one
# connection would silently leak into whichever client gets that
# connection next. The codebase doesn't use .iterator() today, so this
# has no behavioral effect right now — it's a guardrail against
# introducing one later while pooling is in place, not a workaround for
# an existing usage.
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

# ---------------------------------------------------------------------------
# Security headers for production
# ---------------------------------------------------------------------------
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Required behind a reverse proxy (nginx, AWS ALB, etc.) that terminates
# TLS and forwards plain HTTP internally. Without this, Django never sees
# the request as HTTPS and SECURE_SSL_REDIRECT causes an infinite redirect
# loop, since it keeps "upgrading" a request it thinks is still HTTP.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ---------------------------------------------------------------------------
# CORS: explicit allow-list only — no wildcard in production
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS")

# ---------------------------------------------------------------------------
# Sentry: error tracking + light performance monitoring
# ---------------------------------------------------------------------------
# Optional by design — SENTRY_DSN unset means sentry_sdk.init() is never
# called, so an environment without Sentry configured (a fresh deploy
# target, a local `production` smoke test) runs identically to one that
# never heard of Sentry, instead of failing to start or silently no-op
# initializing with an empty DSN.
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        # Distinguishes staging/prod/etc. in the Sentry UI when the same
        # project DSN is reused across environments.
        environment=env("SENTRY_ENVIRONMENT", default="production"),
        # Expected to be set by the deploy pipeline to the git commit SHA
        # being deployed, so a Sentry issue can be traced back to the
        # exact commit that shipped it. None is a valid value — Sentry
        # just omits release tagging rather than erroring.
        release=env("SENTRY_RELEASE", default=None),
        # 10% of requests get full performance traces. This is a cost/
        # signal trade-off, not a correctness one — every *error* is
        # still captured regardless of this setting; this only controls
        # transaction/performance sampling. Raise it if perf debugging
        # becomes a priority and the Sentry quota allows it.
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.1),
        # This project's User model stores email addresses, and request
        # bodies for auth endpoints carry passwords — don't let the SDK's
        # default PII capture (IP addresses, request bodies with
        # cookies/headers) forward any of that to Sentry.
        send_default_pii=False,
    )
