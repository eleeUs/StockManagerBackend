# Phase 9 — Bugfix plan for the 4 remaining test-failure groups

## Status: CLOSED — all 4 groups fixed and verified against real Postgres output.

Final numbers, verified: venta 14, transferencia-create 15,
transferencia-confirm 18. `apps/movements/tests/test_query_count.py`
updated to assert these exact counts, with per-query breakdowns in
each docstring instead of the old unverified estimates.

Coverage after this round: 88.89% (well above the 65% interim floor).
Worth raising `--cov-fail-under` in `pytest.ini` now that there's a
stable, verified baseline — suggest 85% as the next floor, leaving a
few points of margin rather than pinning it to the exact current
number.

Context: after fixing the `apps/users/urls.py` routing bug (`../users/`
→ `/api/v1/users/`), `test_permissions.py` went from 9 failures to 35/35
passing. This document covers the other 4 groups from the original
18-failure baseline run.

Confidence varies by group — marked explicitly below. Where I could
confirm a root cause by reading the code, I say so and give the fix.
Where I could not (no Postgres access in this environment), I say
that too, and give a concrete way to finish the diagnosis instead of
guessing.

---

## Group 1 — Audit trail: `test_role_reassignment_creates_audit_log_entry`

**Confidence: high, but unverified — likely already fixed by the routing fix.**

The test does:
```python
client.patch(f"/api/v1/users/{seller.id}/", {"full_name": "New Name"})
entry = AuditLog.objects.get(model_name="User", object_id=seller.id)
```

`UserDetailView` (`apps/users/views.py`) already correctly uses
`AuditedUpdateMixin` with `audit_model_name = "User"` — the audit
logic itself was never broken. But before the routing fix,
`/api/v1/users/{id}/` didn't exist (404), so the `PATCH` never
reached `perform_update()`, no `AuditLog` row was ever created, and
`.get()` raised `DoesNotExist`. This is almost certainly the exact
same root cause as the `test_permissions.py` failures, not a
separate bug in the audit code.

**Action:** re-run this test in isolation before doing anything else:
```bash
docker-compose exec api pytest apps/audit/tests/test_audit_trail.py -v
```
If it now passes, no code change is needed here — close this item.
If it still fails, the failure mode has changed and needs fresh
diagnosis (paste the new traceback).

---

## Group 2 — Login throttle: `test_login_throttled_after_limit`

**Confidence: high — root cause identified in DRF's own throttle mechanics.**

```python
with patch("core.views.LoginRateThrottle.allow_request", return_value=False):
    response = client.post("/api/v1/auth/login/", {...})
assert response.status_code == 429
```

`AttributeError: 'LoginRateThrottle' object has no attribute 'history'`

This is a **test bug, not an app bug**. DRF's `SimpleRateThrottle.allow_request()`
sets `self.history` as its first action (reading prior request
timestamps from cache). By mocking `allow_request` to unconditionally
`return_value=False`, the test skips that assignment entirely.
`APIView.check_throttles()` then calls `throttle.wait()` on the same
instance to compute the `Retry-After` header for the 429 response —
and `wait()` reads `self.history`, which was never set. Confirmed
by checking `core/views.py::LoginRateThrottle` (inherits directly
from `AnonRateThrottle`, no `history` override) and the mock's
`return_value=False` form (no `side_effect`, so `self.history` is
never touched).

**Fix — in the test, not in `core/views.py`:**
```python
with patch("core.views.LoginRateThrottle.allow_request", return_value=False), \
     patch("core.views.LoginRateThrottle.wait", return_value=60):
    response = client.post("/api/v1/auth/login/", {...})
assert response.status_code == 429
```
Patching `wait()` alongside `allow_request()` sidesteps the
uninitialized-state issue entirely, and the test doesn't actually
care what the wait duration is — only that the endpoint returns 429.

**Action:** apply the one-line addition above to
`tests/test_phase5.py::test_login_throttled_after_limit`.
`test_login_throttle_not_applied_to_other_endpoints` (same file,
same mocking pattern) should get the same fix pre-emptively — check
whether it's failing too even though it wasn't in the original list;
if it's only passing by accident (e.g. hits an endpoint that never
reaches `wait()`), it's worth hardening anyway.

---

## Group 3 — `test_null_clears_reorder_point`

**Confidence: high — root cause is a test-client encoding default, confirmed by reading the test.**

```python
response = client.patch(
    f"/api/v1/stock/{stock.id}/reorder-point/", {"reorder_point": None}
)
```

`TypeError: Cannot encode None for key 'reorder_point' as POST data`

DRF's test client defaults to multipart form encoding when no
`format=` is given. Multipart/form-data has no representation for
`None` — only JSON does (`null`). The view and serializer are not at
fault; `StockReorderPointUpdateSerializer.reorder_point` already
declares `allow_null=True` correctly (`apps/stock/serializers.py`),
so once the request actually reaches it as JSON `null`, it should
work as intended.

**Fix — one line, in the test:**
```python
response = client.patch(
    f"/api/v1/stock/{stock.id}/reorder-point/",
    {"reorder_point": None},
    format="json",
)
```

**Action:** apply directly to
`apps/stock/tests/test_reorder_point.py::test_null_clears_reorder_point`.
Worth a quick scan of the rest of that file for the same missing
`format="json"` on other calls that happen to pass today only
because they don't send a `None`.

---

## Group 4 — N+1 queries: `test_query_count.py` (6 failures)

**UPDATE — root cause found and fixed.** See below; this supersedes
the "needs measurement" framing this section originally had.

**Confirmed root cause: `django-silk` was running during test runs.**

`config/settings/development.py` wires in `silk.middleware.SilkyMiddleware`
with `SILKY_PYTHON_PROFILER = True`, and `pytest.ini` pointed
`DJANGO_SETTINGS_MODULE` at `config.settings.development`. Silk
records a `SilkRequest` row plus a `SQLQuery` row for **every SQL
query the app executes**, and the Python profiler adds further
writes on top of that — all inside the same request/response cycle,
on the same DB connection `django_assert_num_queries` is counting.

This explains the numbers precisely: the ratio between "expected" and
"actual" was ~7-8x across every failing test, regardless of which
view or model was involved (movements list: 1→13; stock/product
list: 2→15; venta/transferencia: 6-7→47-51) — a flat multiplier
applied uniformly is exactly what a global profiling middleware
produces, and is not consistent with per-view N+1 bugs, which would
scale with each view's specific relations instead.

It also explains the teardown warning seen in the same run
(`database "test_stock_db" is being accessed by other users`) — Silk's
background write activity was holding connections open past the end
of the test.

**Proof this was it, not a coincidence:** the `select_related("supplier")`
fix applied to `MovementListView` (§4a below) had **zero effect** on
the query count in the next run — same 13, same 12. If a real N+1 had
been there, that fix would have moved the number. It didn't, which
falsifies the original per-view N+1 hypothesis and points squarely at
something applied uniformly to every request — i.e. the middleware.

**Fix:**
1. New `config/settings/test.py`, inheriting from `development.py`,
   strips `silk` out of `MIDDLEWARE`/`INSTALLED_APPS` and disables
   `SILKY_PYTHON_PROFILER`.
2. `pytest.ini` → `DJANGO_SETTINGS_MODULE = config.settings.test`.
3. **Gotcha:** `.env` sets `DJANGO_SETTINGS_MODULE=config.settings.development`,
   and because `docker-compose.yml` loads `.env` via `env_file:`, that
   becomes a real container environment variable — which pytest-django
   prefers over `pytest.ini`. Left alone, step 2 would be silently
   ignored inside Docker. Fixed by forcing the env var explicitly in
   the `Makefile`'s `test`/`test-v`/`coverage` targets
   (`docker-compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest ...`)
   rather than editing `.env` itself (`.env` still correctly points at
   `development` for `runserver`, where Silk's profiling is genuinely
   useful).

**If you run `pytest` manually inside the container** (not via `make`),
prefix the command: `DJANGO_SETTINGS_MODULE=config.settings.test pytest ...`
— otherwise you're back to profiled, inflated query counts.

### 4a. `select_related("supplier")` on `MovementListView`

Still applied (`apps/movements/views.py`) — it's correct hygiene
(the serializer does read `supplier.name`, and relying on `supplier`
happening to be `None` in today's test fixtures is fragile), but it
was **not** the fix for the failing tests. Kept for the record so the
diff doesn't look like a no-op.

### Expected outcome after the Silk fix

Re-run `apps/movements/tests/test_query_count.py` with the corrected
settings. The three venta/transferencia tests may still fail even
after removing Silk's overhead — their docstrings self-flag the
expected counts (6, 6, 7) as unverified estimates. If they fail with
numbers much closer to the estimate (single digits off, not 7-8x),
that's a real discrepancy in the expected count or a genuine smaller
N+1, worth a fresh look with real numbers rather than the
Silk-inflated ones from this round.

### Follow-up round — real SQL captured, two more root causes fixed

With Silk out of the way, `test_movement_list_no_n_plus_one` and
`test_movement_list_seller_scope_no_n_plus_one` passed immediately.
The three venta/transferencia tests still failed, but now at ~3x
instead of ~7-8x, with real SQL attached to the failure. Two genuine,
confirmed redundancies:

**A. `_QuantityValidationMixin._validate_unit_quantity()`
(`apps/movements/serializers.py`) refetched the product by id**, even
though `validate()` already had the fully-loaded instance from
`data["product"]` (populated by the `PrimaryKeyRelatedField` a few
lines earlier in the same request). Changed the method to accept the
instance directly instead of an id, and updated all 6 call sites
(venta, transferencia, ajuste, ingreso, devolucion, donacion
serializers all share this mixin). Saves one query on every
movement-creating endpoint, not just the two that had failing tests.

**B. `VentaView`/`TransferenciaView` (create) serialized the response
straight off the object `.create()` returned**, which only carries raw
FK ids (`product_id`, `source_branch_id`, ...) — not the related
objects. `StockMovementSerializer` reads `product.name`,
`source_branch.name`, etc., so every field access triggered a fresh
SELECT for something already sitting in memory as
`d["product"]`/`d["branch"]` from serializer validation. Fixed by
assigning the already-validated instances onto the movement's FK
cache before serializing (`movement.product = d["product"]`, etc.) —
zero extra queries instead of one query saved per field.

**C. `StockMovementService.confirmar_transferencia()` only had
`select_related("product")`** on the row-locking fetch, missing
`source_branch`, `destination_branch`, `created_by` — all of which
`StockMovementSerializer` reads. Added them to the same
`select_related()` call (consistent with the `MovementListView` fix
in §4a below).

**Known follow-up, not yet applied:** fix B's pattern (assign
validated instances onto the FK cache before serializing) almost
certainly exists identically in `IngresoView`, `AjusteView`,
`DevolucionView`, and `DonacionView` — they all follow the same
"validate → call service with `.id`s → serialize `.create()`'s
return value" shape. None of them have a failing
`django_assert_num_queries` test today, so they weren't touched here
to keep this diff scoped to what's actually verified. Worth a
deliberate pass applying the same one-line fix to all four, ideally
alongside adding query-count tests for them (they currently have none).

**Not yet reconciled: the test's expected counts (6, 6, 7) themselves.**
Hand-counting the remaining query list after fixes A-C (see raw SQL
in the shared test output) lands around 14 / 15 / 17 — still well
above the docstring's original estimate, but that estimate never
accounted for two structural, non-bug costs: (1) SAVEPOINT/RELEASE
pairs from the nested `transaction.atomic()` blocks (outer
idempotency wrapper + inner business-logic transaction — 3 pairs, 6
statements, on venta), and (2) the idempotency layer's own two
queries (lock-check SELECT + INSERT) on every mutating request. These
are the cost of the idempotency + row-locking design, not a
regression to chase further.

**Action:** re-run `test_query_count.py` with fixes A-C applied,
confirm the actual numbers, and update the three tests' expected
counts to match reality — with a comment explaining the
savepoint/idempotency baseline, so a future 6→14 diff doesn't read as
an unexplained regression to whoever looks at this next.

### Incident: fix C caused a real regression, now corrected

The first version of fix C (`select_related("product", "source_branch",
"destination_branch", "created_by")` combined with `select_for_update()`
in `confirmar_transferencia`) broke 10 tests with
`NotSupportedError: FOR UPDATE cannot be applied to the nullable side
of an outer join`. `source_branch`, `destination_branch`, and
`created_by` are nullable at the model level (other movement types
don't populate all of them), so Django generates a LEFT OUTER JOIN
for each — and Postgres refuses to lock rows through the nullable
side of an outer join, regardless of what the actual data looks like
for a transferencia specifically.

**Corrected fix:** the locked fetch now only does
`select_related("product")` — `product` is a required (NOT NULL) FK,
safe to join under `FOR UPDATE`. A second, unlocked `select_related()`
fetch (all four relations) runs after `transaction.atomic()` exits,
purely for the response serializer — safe because the mutation already
committed by that point; nothing left to protect with a row lock.
Net effect: 3 separate post-commit SELECTs collapsed into 1, instead
of the originally-intended 0 — expect `test_transferencia_confirm_query_count`
to land around 18, not 17.

Every other `select_for_update()` call in `services.py` was audited
(`grep -n "select_for_update()"`) — none of the others combine it with
`select_related()`, so this was an isolated case, not a pattern to
hunt for elsewhere.

---

## Suggested order of implementation

1. Group 1 — just re-run, likely free (no code change).
2. Group 3 — one-line test fix, zero risk.
3. Group 2 — one-line test fix, zero risk.
4. Group 4a — one-line production fix (`select_related`), re-run full
   `test_query_count.py` before moving on, since it may shrink or
   resolve 4c's numbers too.
5. Group 4b/4c — needs an actual Postgres run with query capture;
   can't be finished from static reading alone.
