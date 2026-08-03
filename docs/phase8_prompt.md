# Phase 8 — Prompt: Idempotency + Extended Audit Trail (3 Parts)

You are a senior backend developer continuing the stock management system.
The project is at the end of Phase 7 (pricing, suppliers, reorder alerts).
This document specifies Phase 8 in three deliberately separated parts.

**Read this whole document before writing code in any part.** The parts
build on each other and Part 1's design decisions constrain what Part 2 and
Part 3 are allowed to do.

---

## Why three parts instead of one

Phases 1–7 were all strictly additive — nothing broke previously-working
behavior or previously-passing tests. Phase 8 is different: making
`Idempotency-Key` mandatory on every stock-mutating endpoint is a
deliberate breaking change to the API contract, and it invalidates
query-count contracts that Phase 4 documented as architecture, not just as
tests.

Doing all of that in one pass makes the diff unreviewable and makes it
hard to tell "the new feature is wrong" apart from "an unrelated existing
test broke because I touched something adjacent." Splitting it isolates
risk:

- **Part 1** ships new code with zero behavior change to any existing
  endpoint. If Part 1 is wrong, nothing that currently works is affected.
- **Part 2** is the actual breaking change, isolated to nine views and
  their schemas — nothing else.
- **Part 3** is entirely fallout and a second, unrelated feature
  (audit trail) that doesn't depend on Part 1/2 being perfect, only
  merged.

Each part must be independently reviewable, independently testable, and
the codebase must be in a working, fully-green state at the end of each
part — not just at the end of Part 3.

---

## Part 1 — Idempotency Foundations (non-breaking)

### Goal

Build the entire idempotency mechanism as inert infrastructure. At the end
of Part 1, `apps/idempotency/` exists, is fully tested in isolation, and
**is not wired into a single existing view**. Every Phase 1–7 endpoint
behaves exactly as before. This part should be safe to merge on its own
with no functional review risk beyond "does the new isolated code work."

### New app: `apps/idempotency/`

Register in `LOCAL_APPS` in `config/settings/base.py`, after
`apps.users` (it has no dependency on `products`/`stock`/`movements`, and
those apps will depend on it starting in Part 2).

### Model

```python
class IdempotencyKey(models.Model):
    user             = models.ForeignKey("users.User", on_delete=models.CASCADE,
                                          related_name="idempotency_keys")
    key              = models.CharField(max_length=255)
    endpoint         = models.CharField(max_length=255)  # request.path
    request_hash     = models.CharField(max_length=64)   # sha256 hex of the body
    response_status  = models.PositiveSmallIntegerField()
    response_body    = models.JSONField()
    created_at       = models.DateTimeField(auto_now_add=True)
    expires_at       = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "key", "endpoint"],
                name="idempotency_key_unique_per_user_endpoint",
            )
        ]
        indexes = [models.Index(fields=["expires_at"])]  # for the cleanup command
```

**Design decision to preserve, don't "improve" on it later:** a row is
only ever written to this table **after** the wrapped business operation
succeeds. There is no `status="processing"` field and no state machine.
This is deliberate, not an oversight — see the "Why no status field"
rationale below. If a future part of this project reintroduces one,
that's a sign the transaction boundary in the mixin has been broken.

`response_status`/`response_body` are **not nullable** — a row without a
successful response has no reason to exist.

### Service (`apps/idempotency/services.py`)

Mirror the naming and structure already used in
`apps/movements/services.py` (`_lock_stock`, `_get_or_create_and_lock_stock`)
rather than inventing a different style:

```python
class IdempotencyService:

    @staticmethod
    def hash_body(data: dict) -> str:
        """sha256 hex digest of a canonical (sorted-key) JSON dump of the
        request body. Used to detect key reuse against a different
        request, not to detect exact duplicates of the row itself."""

    @classmethod
    def get_or_create_and_lock(cls, *, user, key, endpoint, request_hash) -> tuple[IdempotencyKey | None, bool]:
        """
        MUST be called inside transaction.atomic() by the caller.

        Returns (existing_row_or_None, created: bool).

        - created=True  → no prior row. Caller proceeds with the business
          operation and must call store_response() before the transaction
          commits.
        - created=False → a prior row exists for this (user, key, endpoint).
          select_for_update() has already been used to lock it, so by the
          time this returns, its data is final (see rollback semantics
          below — a row only exists if it represents a completed success).
          - If request_hash doesn't match → raise IdempotencyKeyConflictError.
          - Otherwise → this is a legitimate replay; the caller must return
            the stored response without re-running any business logic.
        """

    @staticmethod
    def store_response(row: IdempotencyKey, *, response_status: int, response_body: dict) -> None:
        """Populates response_status/response_body on a freshly created row."""
```

### Why no `status` field — rollback semantics (read this before implementing the mixin in Part 2)

The mixin in Part 2 will wrap the **entire** request handling — header
validation, `get_or_create_and_lock`, the call into the view's business
logic, and `store_response` — inside a single `transaction.atomic()`
block.

The service layer (`StockMovementService.venta`, `.ingreso`, etc.) opens
its *own* `transaction.atomic()` internally. Nesting is fine — Django
turns the inner block into a savepoint. What this buys us:

- If the business operation succeeds, the outer transaction commits and
  the `IdempotencyKey` row commits with it, atomically, in the same
  transaction as the stock mutation it's caching.
- If the business operation raises a domain exception (e.g.
  `InsufficientStockError`), **the entire outer transaction must roll
  back**, including the `IdempotencyKey` row that was about to be
  created. This is what makes the "no status field" design correct: a
  row can only ever exist in a state that represents a real, committed
  success. A retry after a genuine failure is not a replay of a cached
  response — it's a fresh attempt against (possibly changed) state, and
  it must be allowed to actually re-run.

**The trap to avoid in Part 2:** DRF's `APIView.dispatch()` catches
exceptions internally via `self.handle_exception()` and returns a normal
`Response` object — the exception does **not** propagate out of
`dispatch()`. Wrapping `super().dispatch()` in `transaction.atomic()` and
relying on a raised Python exception to trigger rollback **will not
work** for domain errors that `custom_exception_handler` already
translates into a 400 response. The mixin must explicitly check the
response after calling `super().dispatch()` and call
`transaction.set_rollback(True)` if `response.status_code >= 400`, before
the `atomic()` context manager exits. Write a test in Part 1 (against a
throwaway view, or directly against the service function) that proves
this rollback behavior before Part 2 wires it into real endpoints.

### Domain exceptions (`core/exceptions.py`)

Add alongside the existing `StockDomainError` hierarchy, but as a
**separate** base — these aren't stock-domain errors, they're a
cross-cutting HTTP concern:

```python
class IdempotencyError(Exception):
    """Base for all idempotency-layer exceptions."""
    pass

class IdempotencyKeyRequiredError(IdempotencyError):
    """Raised when Idempotency-Key is required and missing. → HTTP 400."""
    pass

class IdempotencyKeyConflictError(IdempotencyError):
    """Raised when a key is reused with a different request body. → HTTP 409."""
    pass
```

Extend `custom_exception_handler` with two more `isinstance` branches,
following the exact pattern already used for `InsufficientStockError`
etc. Error codes: `"idempotency_key_required"` and
`"idempotency_key_conflict"`.

### Mixin (`apps/idempotency/mixins.py`)

`IdempotentMutationMixin` — built and unit-tested in Part 1, **not
applied to any view yet**. Key behaviors to get right now so Part 2 is a
pure wiring exercise:

- Only intercepts `POST` (the write endpoints in this project are all
  `POST`; don't add complexity for methods that don't need it).
- Reads the `IDEMPOTENCY_KEY_REQUIRED` setting (see below) to decide
  whether a missing header is an error or a no-op passthrough.
- Uses `request.path` as `endpoint` and `request.user` as `user` — both
  are guaranteed resolved at this point because DRF authentication has
  already run by the time a view's `dispatch()`/`post()` executes (this
  is *why* this is a DRF mixin and not a Django middleware — a
  middleware runs before JWT auth resolves `request.user`).

### Settings

```python
# config/settings/base.py
IDEMPOTENCY_KEY_REQUIRED = env.bool("IDEMPOTENCY_KEY_REQUIRED", default=True)
```

Add `IDEMPOTENCY_KEY_REQUIRED=True` to `.env.example`. This is an
operational escape hatch, not a relaxation of the business rule — the
default is `True` everywhere, including this default value itself.
Document in `docs/BUSINESS_RULES.md` (Part 2) that flipping it to `False`
is an emergency operational lever, not a supported steady state.

### Tests (Part 1 scope only)

All of these test `apps/idempotency/` in isolation — no HTTP layer, no
existing view:

- `IdempotencyService.hash_body` is deterministic and order-independent
  (`{"a": 1, "b": 2}` and `{"b": 2, "a": 1}` hash the same).
- `get_or_create_and_lock` returns `created=True` on first call.
- Second call with the same `(user, key, endpoint)` and matching hash
  returns `created=False` and the existing row.
- Second call with a mismatched hash raises `IdempotencyKeyConflictError`.
- **Rollback test (the important one):** wrap a call that raises
  `InsufficientStockError` (or any domain exception) inside the same
  `transaction.atomic()` pattern the mixin will use in Part 2, assert
  that no `IdempotencyKey` row exists afterward. This is the test that
  proves the design in the section above is actually correct before
  Part 2 depends on it.
- A concurrency test with real threads (`TransactionTestCase`, same
  pattern as `TestConcurrentVenta` in `apps/movements/tests/test_services.py`):
  two threads call `get_or_create_and_lock` with the same key
  simultaneously; exactly one gets `created=True`.

### Part 1 deliverables checklist

- [ ] `apps/idempotency/` app scaffolded and registered in `LOCAL_APPS`
- [ ] `IdempotencyKey` model + initial migration
- [ ] `IdempotencyService` with `hash_body`, `get_or_create_and_lock`, `store_response`
- [ ] `IdempotencyError`, `IdempotencyKeyRequiredError`, `IdempotencyKeyConflictError` in `core/exceptions.py` + handler mapping
- [ ] `IdempotentMutationMixin` in `apps/idempotency/mixins.py`, built but not applied anywhere
- [ ] `IDEMPOTENCY_KEY_REQUIRED` setting + `.env.example` entry
- [ ] Full test suite for the above, including the rollback test and the concurrency test
- [ ] **Verification step:** run the full existing test suite (`pytest --tb=short -q`) and confirm zero changes in pass/fail status vs. the end of Phase 7. If anything changed, Part 1 touched something it shouldn't have.

---

## Part 2 — Enforcement (the breaking change)

### Goal

Wire `IdempotentMutationMixin` into the nine stock-mutating views. This
is the part where the API contract actually changes. Scope is limited to
these nine views, their `@extend_schema` decorators, and
`BUSINESS_RULES.md` — nothing else changes in this part.

### Views to update (`apps/movements/views.py`)

```
IngresoView
VentaView
AjusteView
DevolucionView
DonacionView
TransferenciaView
ConfirmTransferView
CancelTransferView
ReverseMovementView
```

Add `IdempotentMutationMixin` to each class's bases. Confirm the mixin's
placement in the MRO doesn't interfere with `permission_classes` — the
idempotency check should happen **after** permission checks, not before
(a seller hitting an admin-only endpoint should still get `403`, not a
`400` about a missing header — don't leak information about the
idempotency requirement to a caller who isn't authorized to call the
endpoint at all).

### OpenAPI schema updates

Every `@extend_schema` on the nine views above needs the header
documented as required:

```python
parameters=[
    OpenApiParameter(
        "Idempotency-Key", OpenApiTypes.STR, OpenApiParameter.HEADER,
        description="Client-generated unique key (e.g. a UUID) for safe retries. Required.",
        required=True,
    ),
    # ...existing parameters
],
responses={
    # ...existing responses
    400: OpenApiResponse(description="Missing or malformed Idempotency-Key."),
    409: OpenApiResponse(description="Idempotency-Key reused with a different request body."),
},
```

### `BUSINESS_RULES.md` — new §12

Document, plainly:

- `Idempotency-Key` is required on every stock-mutating endpoint (list
  them explicitly).
- What happens on replay (same key, same body → same cached response,
  no re-execution).
- What happens on conflict (same key, different body → `409`, nothing
  executes).
- The `IDEMPOTENCY_KEY_REQUIRED` setting exists as an operational escape
  hatch and is not a supported steady state.
- **State the trade-off honestly**: this protects against network-level
  retries duplicating a movement. It does not protect against a client
  that never sends the header failing to enable this protection at
  all — that's not possible with a per-request opt-in header, which is
  exactly why it's mandatory instead of optional.

### Tests to add in Part 2 (new behavior only — do not touch the ~40 existing failing call sites yet, that's Part 3)

A **small**, new, isolated set of integration tests proving the wiring
works end-to-end against one representative endpoint (`VentaView` is
enough — the mixin is shared code, you're not re-testing the mixin
itself, just proving it's actually attached):

- Missing header on a mutating endpoint → `400`, error code
  `idempotency_key_required`.
- Same header + same body sent twice → second response is byte-identical
  to the first, and `Stock.quantity` only changed once.
- Same header + different body sent twice → second response is `409`,
  `Stock.quantity` unchanged by the second call.
- With `IDEMPOTENCY_KEY_REQUIRED=False` (via `settings` override in the
  test), missing header no longer errors — endpoint behaves like Phase 7.

### Part 2 deliverables checklist

- [ ] `IdempotentMutationMixin` applied to all nine views listed above
- [ ] Mixin ordering confirmed not to leak permission info (403 still wins over 400)
- [ ] All nine `@extend_schema` updated with the header parameter + 400/409 responses
- [ ] `docs/BUSINESS_RULES.md` §12 written
- [ ] New wiring tests (above) passing
- [ ] **Expected and accepted at the end of this part:** the ~40 existing
      call sites across `test_permissions.py`, `test_query_count.py`,
      `test_supplier_ingreso.py`, and `test_reversals.py` are now failing
      with `400 idempotency_key_required`. This is the known, scoped
      blast radius from the cost analysis — do not fix it in Part 2.
      Confirm the failures are *only* `400`s from missing headers, not
      something else (that would indicate the mixin broke something
      beyond its intended scope).

---

## Part 3 — Fallout Cleanup + Extended Audit Trail

### Goal

Bring the test suite back to fully green, correct the query-count
contracts that Part 2 invalidated, add the operational cleanup command,
and then deliver the second, unrelated pillar of Phase 8: an audit trail
for `Product`, `Branch`, and `User`.

### 3.1 — Fix the ~40 call sites

Add a small test helper rather than hand-editing every call site
individually — but note this still means touching every call site, just
mechanically:

```python
# tests/helpers.py
import uuid

def idempotent_post(client, url, data=None, **kwargs):
    """
    POST with an auto-generated Idempotency-Key. Use for any call to a
    stock-mutating endpoint in a test where key reuse isn't the point of
    the test. Tests that specifically test replay/conflict behavior
    (Part 2) should keep constructing the header manually.
    """
    key = kwargs.pop("idempotency_key", None) or str(uuid.uuid4())
    return client.post(url, data, HTTP_IDEMPOTENCY_KEY=key, **kwargs)
```

Update every call site currently doing `client.post("/api/v1/movements/...", {...})`
in:
- `apps/movements/tests/test_permissions.py`
- `apps/movements/tests/test_query_count.py`
- `apps/movements/tests/test_supplier_ingreso.py`
- `apps/movements/tests/test_reversals.py`

**Do not** add a default header via `client.credentials(...)` in the
`admin_client`/`seller_client` fixtures — several existing tests reuse the
same client for two logically distinct write calls in one test (e.g.
create-transfer then confirm-transfer in `test_permissions.py`). A
fixture-level static key would make those two calls collide and trigger
a spurious `409`, which is a worse failure mode than the one being fixed.
Each call site needs its own key — that's what `idempotent_post` is for.

### 3.2 — Correct the query-count contracts

`test_venta_query_count`, `test_transferencia_create_query_count`, and
`test_transferencia_confirm_query_count` in
`apps/movements/tests/test_query_count.py` will need new numbers. **Do
not guess the new numbers and hardcode them** — run the tests locally
against the Part 1+2 implementation, read the actual query count
`django_assert_num_queries` reports on failure, and use that. Then:

- Update the three assertions.
- Update the inline docstring in each test explaining what the queries
  are (following the existing style — see the current docstring on
  `test_transferencia_confirm_query_count` for the format).
- Update `docs/phase-4.md`, which documents these counts as part of the
  architecture, not just as test internals — it will otherwise describe
  a system that no longer matches what's running.
- Add one line to `docs/phase-8.md` (below) noting that these contracts
  changed and why (idempotency lock + response persistence adds queries
  to every mutating endpoint).

### 3.3 — `cleanup_idempotency_keys` management command

Same shape as `check_low_stock` from Phase 7 — cron-facing, no task
queue:

```bash
python manage.py cleanup_idempotency_keys
python manage.py cleanup_idempotency_keys --dry-run
```

Deletes `IdempotencyKey` rows where `expires_at < now()`. Use the
`expires_at` index already defined on the model in Part 1.

### 3.4 — Audit trail for `Product`, `Branch`, `User`

This is the second half of the original Phase 8 scope from the roadmap,
independent of everything above — it doesn't touch idempotency at all.

- New `AuditLog` model — **not** `django-simple-history`, and **not**
  `GenericForeignKey`. See the earlier design discussion for why: the
  library's default user-capture middleware doesn't cooperate with
  JWT-inside-DRF without extra plumbing, and `GenericForeignKey` adds a
  `django_content_type` join this project doesn't need for a simple
  "who changed what" log.

  ```python
  class AuditLog(models.Model):
      model_name  = models.CharField(max_length=50)   # "Product", "Branch", "User"
      object_id   = models.PositiveIntegerField()
      action      = models.CharField(choices=["create", "update", "deactivate"])
      changed_by  = models.ForeignKey("users.User", on_delete=models.PROTECT)
      changes     = models.JSONField()                # {"field": {"old": ..., "new": ...}}
      created_at  = models.DateTimeField(auto_now_add=True)

      class Meta:
          indexes = [models.Index(fields=["model_name", "object_id", "created_at"])]
  ```

- Captured **explicitly in the view/serializer layer**, at the point
  `request.user` is already known — not via `pre_save`/`post_save`
  signals, which have no reliable access to the current user without
  thread-local state.
- Wire into the existing admin-only update paths for `Product`, `Branch`,
  and `User` — diff the fields that actually changed (old value from the
  fetched instance before `.save()`, new value from the validated
  serializer data) and write one `AuditLog` row per mutating request.
- Read-only endpoint: `GET /api/v1/audit-log/?model=Product&object_id=5`
  (admin only) to actually query it — an audit trail nobody can read
  isn't useful.

### Part 3 deliverables checklist

- [ ] `tests/helpers.py::idempotent_post` added
- [ ] All ~40 call sites across the four affected test files updated
- [ ] Full suite green: `pytest --tb=short -q` passes with zero failures
- [ ] `test_query_count.py`'s three affected assertions updated with real,
      measured numbers (not estimated)
- [ ] `docs/phase-4.md` updated to match
- [ ] `cleanup_idempotency_keys` command + a test for it (dry-run and real delete)
- [ ] `AuditLog` model + migration, in a new `apps/audit/` app
- [ ] Audit capture wired into `Product`, `Branch`, `User` admin-only update paths
- [ ] `GET /api/v1/audit-log/` read endpoint, admin only, with `@extend_schema`
- [ ] `docs/phase-8.md` written (same style as phase-1 through phase-7),
      covering both idempotency and the audit trail, and explicitly
      calling out the query-count contract change as a deliberate,
      measured trade-off
- [ ] `docs/commits.md` updated with conventional commits for all three parts

---

## Code conventions to follow strictly (unchanged from prior phases)

- Views: `@extend_schema` on every `APIView`, never on `GenericAPIView`
  (already auto-documented). Access control via `permission_classes`.
- Write serializers are plain `serializers.Serializer`, not
  `ModelSerializer`, when the input shape doesn't map 1:1 to a model —
  `IdempotencyKey` is never exposed through a serializer to clients at
  all, it's an internal mechanism.
- Test data exclusively from `tests/factories.py` / new factories added
  there, never `Model.objects.create(...)` directly in test files.
- One assertion per test where possible.
- Do not use `depth=` on any `ModelSerializer.Meta`.
- Do not add Redis, Celery, or any other new infrastructure dependency —
  both the idempotency store and the audit log are plain PostgreSQL
  tables, consistent with everything else in this project.
- No existing migration file is modified. Every schema change in every
  part is a new migration.
