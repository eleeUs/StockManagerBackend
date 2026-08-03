# Phase 6 — Reporting, Security Hardening, and CI/CD

## Overview

Phase 6 closes out the backend with the pieces that turn a working API into
an operable one: read-only reporting endpoints for day-to-day decisions
(what's low on stock, what happened last month), CORS configuration for a
future frontend, the two production security settings that were still
missing, a CI pipeline that gates merges on lint and test results, and
developer-experience tooling (`Makefile`, multi-stage `Dockerfile`).

No existing model, service, or view from Phases 1–5 was modified. Everything
here is additive.

---

## What Was Built

### Reporting (`apps/reports`)

`apps/reports` is deliberately **not** registered in `INSTALLED_APPS`. It has
no models — every report is a pure aggregation over `Stock` and
`StockMovement` — so it needs no migrations and Django never needs to know
about it as an app. URLs, views, and serializers still import and function
normally; app registration is only required for models, admin, and signals.

#### A1 — Low stock report

```
GET /api/v1/reports/stock/low/?threshold=10&branch=2
```

Reuses `StockSerializer` and `StandardPagination` — no new serialization
logic. The interesting decision here is branch scoping: the general
`GET /stock/` endpoint intentionally gives sellers **global** read visibility
(`BUSINESS_RULES §1.2` — a seller needs to see stock elsewhere before asking
for a transfer). A *restock report*, by contrast, only makes sense for the
seller's own branch — nobody needs a low-stock alert for a branch they don't
work at. So `LowStockReportView` scopes sellers via
`BranchScopeQuerysetMixin.get_branch_q()`, the same mechanism used by
`MovementListView`, rather than duplicating a `branch=user.branch` filter
inline.

#### A2 — Movement summary report

```
GET /api/v1/reports/movements/summary/?date_from=2026-01-01&date_to=2026-01-31&branch=2
```

A single `annotate(count=Count("id"), total_quantity=Sum("quantity"))` grouped
by `movement_type`. `date_from` and `date_to` are required — an unbounded
aggregation over the entire ledger is never the right default for a report
endpoint. The existing `idx_movement_type_date` index covers the query
pattern; no new index was added.

#### A3 — Branch activity report

```
GET /api/v1/reports/branches/{id}/activity/?date_from=...&date_to=...
```

Combines the same `summary_by_type` shape as A2 with a `daily_breakdown`
grouped by `TruncDate("created_at")` + `movement_type`. Both admin-only
endpoints return `400` on missing/malformed dates (via DRF's
`ValidationError`, which flows through the existing
`custom_exception_handler`) and A3 returns `404` for an unknown branch id
via `get_object_or_404`.

All three views carry `@extend_schema` with `tags=["Reports"]`, following the
same pattern as `apps/movements/views.py`.

### CORS and security hardening

`django-cors-headers` is installed with a fail-safe default:
`CORS_ALLOW_ALL_ORIGINS = False` and an empty allow-list in `base.py`.
`development.py` opens it fully for local frontend work.
`production.py` reads an explicit comma-separated list from
`CORS_ALLOWED_ORIGINS`. `CorsMiddleware` is placed immediately before
`CommonMiddleware`, which is the position the library requires.

Two settings were missing from `production.py` and are now present:

- `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` — required
  once the app sits behind a TLS-terminating reverse proxy (nginx, an AWS
  ALB). Without it, Django never recognises the request as HTTPS and
  `SECURE_SSL_REDIRECT` (already enabled) creates a redirect loop, since
  every request looks like plain HTTP to Django even after the proxy
  upgraded it.
- `SECURE_HSTS_PRELOAD = True` — allows the domain to be submitted to
  browser HSTS preload lists, so the very first request a browser ever makes
  to the domain is forced over HTTPS, not just subsequent ones.

`.dockerignore` was added to keep `.env`, `.git`, caches, and `docs/` out of
the build context. `requirements/` is intentionally **not** excluded since
it's read during the image build.

### CI/CD (`.github/workflows/ci.yml`)

Two jobs run in parallel on every push and PR to `main` and `develop`:

- **`lint`** — no database needed. Installs `ruff` and runs
  `ruff check .` then `ruff format --check .`.
- **`test`** — spins up a `postgres:16-alpine` service container with a
  `pg_isready` healthcheck, installs `requirements/development.txt`, applies
  migrations, and runs `pytest --tb=short -q`.

Ruff configuration lives in `pyproject.toml` at the project root
(line length 100, target `py312`, `E/F/I/W` rule sets, `E501` ignored since
line length is already enforced by the formatter rather than the linter).

### Makefile and multi-stage Dockerfile

The `Makefile` wraps the `docker-compose exec` commands the team already
runs by hand (`migrate`, `seed`, `test`, `lint`, `shell`, `logs`) plus
lifecycle commands (`build`, `up`, `down`, `prod-up`). All targets are
`.PHONY` since none of them produce a file with that name.

The `Dockerfile` is now two stages:

- **`builder`** (`python:3.12-slim`) installs `gcc`, `libffi-dev`, and
  `libpq-dev`, then runs `pip install --prefix=/install` so compiled
  dependencies land in an isolated directory rather than the system site
  packages.
- **`runtime`** (`python:3.12-slim`) copies only `/install` from the builder
  stage into `/usr/local` — no compiler toolchain ships in the final image.
  This is safe because `psycopg2-binary` bundles its own `libpq` and
  `argon2-cffi` ships prebuilt wheels for this platform; neither needs the
  apt packages at runtime, only at build time.

`ARG REQUIREMENTS=development` is declared in both stages, since Docker
scopes build args to the stage they're declared in — a stage that doesn't
redeclare an `ARG` from an earlier stage simply doesn't see it.

---

## Key Technical Decisions

| Decision | Choice | Reason |
|---|---|---|
| `apps/reports` in `INSTALLED_APPS` | Not registered | No models → no migrations needed; app registration is for that, not for importability |
| Low stock report branch scope | Seller scoped to own branch | Different intent from `GET /stock/`'s deliberate global read visibility (§1.2) |
| Report date params | Required, not defaulted | An unbounded aggregation over the full ledger is never a safe default |
| Report serializers | Plain `serializers.Serializer` | Aggregated dict output has no 1:1 model mapping |
| CORS default | Locked down (`False` / `[]`) | Fail-safe default; each environment opts in explicitly |
| Dockerfile | Multi-stage | Keeps `gcc`/`libffi-dev`/`libpq-dev` out of the runtime image |
| CI test job | `postgres:16-alpine` service container | Mirrors `docker-compose.yml`'s Postgres version for parity between CI and local dev |

---

## Endpoints Introduced

```
GET   /api/v1/reports/stock/low/
GET   /api/v1/reports/movements/summary/
GET   /api/v1/reports/branches/{id}/activity/
```

---

## Running Phase 6 Locally

```bash
# Rebuild — Dockerfile changed (multi-stage) and a new dependency was added
make build
make up
make migrate

# Reports tests
docker-compose exec api pytest apps/reports/tests/test_reports.py -v

# Lint, matching what CI runs
docker-compose exec api ruff check .
docker-compose exec api ruff format --check .

# Full suite
make test
```
