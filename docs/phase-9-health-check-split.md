# Phase 9 — Splitting `/health/` into `/health/live/` and `/health/ready/`

## Status: Planned, not yet implemented

## Why split a single endpoint into two

`GET /health/` today (`core/views.py::HealthCheckView`) always runs
`SELECT 1` against Postgres before answering. That conflates two
different questions that a Kubernetes-style orchestrator (or any
process supervisor) needs answered separately:

- **Liveness** — "Is the Django process itself alive and able to
  respond to a request?" If the answer is no, the correct remedy is
  to **restart the process**.
- **Readiness** — "Is this instance currently able to serve real
  traffic?" If the answer is no, the correct remedy is to **pull it
  out of the load balancer**, not restart it.

With a single DB-checking endpoint wired to both liveness and
readiness probes, a slow or temporarily unreachable Postgres (a
deploy, a failover, a connection-pool exhaustion spike) makes the
liveness probe fail too. The orchestrator concludes the *process* is
broken and restarts it — which does nothing to fix the database, adds
process-startup load on top of an already-struggling DB, and can
tip a transient DB blip into a full crash-loop across every replica
at once (they all fail liveness for the same external reason and
restart in lockstep).

The fix is standard practice, not specific to this project: liveness
must only prove the process can respond; only readiness may depend on
external state like the database.

## Proposed design

### `GET /health/live/`
- No dependencies checked. If the view function runs at all and
  returns a response, the process is alive.
- Always `200 {"status": "ok"}` if reachable. There is no failure
  branch to construct — the absence of a response *is* the failure
  signal (timeout / connection refused), which the orchestrator
  already detects on its own.
- Cheapest possible view: no DB cursor, no serializer, no permission
  checks beyond `AllowAny`.

### `GET /health/ready/`
- Runs the existing `_check_database()` (`SELECT 1`), unchanged.
- `200 {"status": "ok", "database": "ok"}` /
  `503 {"status": "error", "database": "unavailable"}`, same shape as
  today.
- This is the one that's allowed to fail when Postgres is down —
  that's the point.

### Backward compatibility: `GET /health/`
- Docker's `HEALTHCHECK` (if configured), any existing uptime
  monitor, and possibly a load balancer config may already point at
  `/health/`. Two options:
  1. **Keep `/health/` as a permanent alias of `/ready/`** (same
     behavior as today). Simplest, zero coordination needed with
     whatever infra currently polls it.
  2. **Deprecate `/health/`** with a sunset date, once every consumer
     (Docker Compose healthcheck, prod LB, uptime monitor) is
     confirmed migrated to the new paths.
- **Recommendation: option 1.** Aliasing costs nothing and removes
  the need to coordinate a cutover across infra we don't fully
  control the timing of (e.g. an external uptime monitor).

## Implementation sketch

`core/views.py`:
- Extract `_check_database()` as a module-level function (or keep as
  a staticmethod on a shared base) so both views can use it without
  inheritance games.
- `LivenessView(APIView)` — trivial, as described above.
- `ReadinessView(APIView)` — thin wrapper around today's
  `HealthCheckView.get()` logic.
- Keep `HealthCheckView` itself as `ReadinessView`'s implementation
  (rename in place) so `/health/` and `/health/ready/` share one code
  path instead of two copies that can drift.

`config/urls.py`:
```python
path("health/",        ReadinessView.as_view(), name="health-check"),   # legacy alias, kept
path("health/live/",   LivenessView.as_view(),  name="health-live"),
path("health/ready/",  ReadinessView.as_view(), name="health-ready"),
```

## Things to decide before implementing (need input)

1. **Docker Compose `healthcheck:`** — if `docker-compose.yml` or
   `docker-compose.prod.yml` define a container-level `HEALTHCHECK`
   pointing at `/health/`, decide whether to point it at `/health/live/`
   instead. A container healthcheck that restarts the container is
   conceptually a liveness check, not a readiness check — using
   `/health/ready/` there would reintroduce the exact problem this
   split is meant to fix.
2. **Where do readiness failures get surfaced?** Confirm whether the
   prod load balancer / reverse proxy is already configured to poll a
   health endpoint and pull the instance out of rotation on failure.
   If nothing currently does that, `/health/ready/` has no consumer
   yet and standing it up is necessary but not sufficient — the LB
   config needs a matching change.
3. **Should readiness eventually check more than the DB?** (e.g.
   migrations applied, cache backend reachable if one gets added later
   for throttling). Out of scope for this pass — flagging so it's a
   deliberate "not yet" rather than an oversight.

## Testing plan

- `/health/live/` — one test: returns 200 regardless of DB state.
  Simulate DB-down (mock `connection.cursor` to raise
  `OperationalError`) and assert liveness still returns 200.
- `/health/ready/` — two tests: DB up → 200, DB down (same mock) →
  503. This is a direct port of whatever test already covers
  `HealthCheckView` today.
- `/health/` — one test confirming it still matches `/health/ready/`'s
  behavior (the alias contract).

## Out of scope for this change

- Fixing the `apps/users/urls.py` routing bug (`../users/`) — unrelated,
  tracked separately.
- The N+1 query regressions in movements/stock/products views —
  unrelated, tracked separately.
- Any change to what `/health/ready/` checks beyond the DB.
