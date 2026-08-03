# Phase 5 — Migrations, Throttling, Password Change, and Production Readiness

## Overview

Phase 5 makes the project deployable. It covers five concerns that are
prerequisites for going to production: migrations so the database schema
actually exists, rate limiting on the login endpoint, a password change flow
for users, a health check endpoint for infrastructure, and gunicorn with a
request ID middleware for observability.

---

## What Was Built

### Migrations

Initial migrations for all five apps, generated in dependency order:

```
branches    → no dependencies
products    → no dependencies
users       → depends on branches, auth
stock       → depends on branches, products
movements   → depends on branches, products, users (AUTH_USER_MODEL)
```

Django resolves cross-app dependencies via the `dependencies` list in each
migration. The `swappable_dependency(settings.AUTH_USER_MODEL)` pattern in
the movements migration ensures it works regardless of which user model is
configured.

**First-time setup:**
```bash
docker-compose exec api python manage.py migrate
docker-compose exec api python manage.py seed_dev_data
```

### Seed data command (`seed_dev_data`)

An idempotent management command that creates a realistic development dataset:
- 3 branches (Downtown, Northside, Westgate)
- 3 categories, 8 products
- Initial stock for every (product, branch) combination
- 1 admin user + 1 seller per branch

Idempotency is implemented with `get_or_create` throughout. Running the
command multiple times produces no duplicate records and no errors.

The `--flush` flag drops all data before seeding. It requires interactive
confirmation (`yes`) to prevent accidental data loss.

### Login rate limiting

`LoginRateThrottle` is a subclass of DRF's `AnonRateThrottle` with `scope="login"`.
It is applied only to `LoginView` via `throttle_classes`, not globally.

```python
class LoginView(TokenObtainPairView):
    throttle_classes = [LoginRateThrottle]
```

Rate: **5 attempts per minute per IP address.**

Why 5/minute:
- A legitimate user who misremembers their password will retry 2–3 times.
  5 attempts per minute provides comfortable headroom without being exploitable.
- At 5 attempts/minute, an attacker needs 833 hours to try 250,000 common
  passwords from a single IP. Combined with Argon2 (~100ms/attempt on the
  server), brute-force attacks are computationally infeasible.

Global throttle rates (all authenticated API endpoints):
- `user`: 200 requests/minute
- `anon`: 20 requests/minute

### Password change (`POST /api/v1/auth/change-password/`)

Available to any authenticated user. Requires the current password for
verification — this prevents a stolen JWT from being used to lock out the
real account owner.

Validation rules enforced in `ChangePasswordSerializer`:
1. `current_password` must match the stored Argon2 hash.
2. `new_password` ≥ 8 characters.
3. `confirm_password` must equal `new_password`.
4. `new_password` must differ from `current_password`.

`set_password()` applies the configured Argon2id hasher automatically.
Only `password` and `updated_at` are written to the database.

Returns **204 No Content** on success. Clients should discard existing tokens
and prompt re-authentication.

### Health check (`GET /health/`)

No authentication required. Returns:
```json
{"status": "ok",    "database": "ok"}      → HTTP 200
{"status": "error", "database": "unavailable"} → HTTP 503
```

The database check executes `SELECT 1` — cheap but sufficient to prove the
connection pool is alive. Used by Docker's `HEALTHCHECK`, load balancers,
and uptime monitoring tools.

### Request ID middleware (`core/middleware.py`)

`RequestIDMiddleware` runs near the top of the middleware stack. For every
request it:
1. Reads `X-Request-ID` from incoming headers (allows upstream tracing).
2. Generates a `uuid4` if no header is present.
3. Attaches the ID to `request.request_id` and thread-local storage.
4. Writes the ID to the `X-Request-ID` response header.
5. Clears the thread-local on response to prevent cross-request leakage.

`RequestIDFilter` is a `logging.Filter` that reads the thread-local ID and
injects it into every log record as `%(request_id)s`. All log lines produced
during a request now include the same ID:

```
INFO 2026-01-15 14:23:01 services [req=a3f2c1d0-...] VENTA: product=5 qty=3
INFO 2026-01-15 14:23:01 views    [req=a3f2c1d0-...] POST 201 /movements/venta/
```

When a user reports an error, the `X-Request-ID` from their browser correlates
directly to a grep in production logs.

### Gunicorn (`gunicorn.conf.py` + `docker-compose.prod.yml`)

**Worker model: sync (pre-fork)**

Django's ORM with `select_for_update()` is not safe with async/greenlet workers
(gevent, eventlet). A worker blocked on a database lock must block its own
thread — not yield control to other coroutines that might attempt the same
lock. Sync workers guarantee this.

**Worker count: `CPU_COUNT × 2 + 1`**

The +1 handles requests while other workers are blocked on DB locks.
Under the transfer flow, a worker holding a `select_for_update` lock while
writing causes others to queue. The extra worker keeps throughput stable.

**Key settings:**
- `max_requests=1000` with jitter: workers restart periodically to prevent
  memory leaks. Jitter prevents all workers from restarting simultaneously.
- `timeout=30`: any request taking more than 30 seconds kills the worker.
  This surfaces runaway queries in production rather than silently blocking.
- `accesslog="-"`: stdout. Docker captures this natively via `docker logs`.

**Production deployment:**
```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

---

## Key Technical Decisions

| Decision | Choice | Reason |
|---|---|---|
| Throttle scope | Only login endpoint | API endpoints throttled globally; login needs a separate stricter limit |
| Rate: 5/min | DRF in-memory cache | No Redis dependency; sufficient for single-instance deployment |
| Password change | Requires current_password | Prevents stolen token from locking out real user |
| Health check | `SELECT 1` only | Cheap; proves connection is live without schema assumptions |
| Middleware position | Second in stack | All subsequent middleware and views have `request.request_id` available |
| Thread-local cleanup | On every response | Gunicorn sync workers reuse OS threads; stale IDs would leak between requests |
| Worker model | sync | `select_for_update()` is incompatible with greenlet-based async workers |

---

## Endpoints Introduced

```
GET    /health/
POST   /api/v1/auth/change-password/
```

---

## First-Time Setup

```bash
# 1. Start services
docker-compose up --build

# 2. Apply all migrations
docker-compose exec api python manage.py migrate

# 3. Seed development data
docker-compose exec api python manage.py seed_dev_data

# 4. Run the test suite
docker-compose exec api pytest --tb=short -q

# Production deployment
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```
