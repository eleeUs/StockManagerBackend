# Phase 8 — Idempotency and Extended Audit Trail

## Overview

Phase 8 is the first phase in this project that deliberately breaks
something. Phases 1–7 were strictly additive; making `Idempotency-Key`
mandatory on every stock-mutating endpoint is a genuine breaking change
to the API contract, done on purpose, because the alternative — an
optional header — protects nobody who doesn't already know to ask for
it. To keep that change reviewable, the work shipped in three parts (see
`docs/phase8_prompt.md` for the original plan): foundations with zero
behavior change, the breaking change itself isolated to nine views, and
then all the fallout plus a second, unrelated feature (an audit trail
for `Product`/`Branch`/`User`) bundled into cleanup.

---

## Part 1 — Idempotency Foundations

### `apps/idempotency/`

A new app: `IdempotencyKey` model, `IdempotencyService`, and
`IdempotentMutationMixin` — built and fully tested in isolation, wired
into precisely zero existing views by the end of Part 1.

### The design that makes rollback correct without a state machine

The model has no `status`/"processing" field. A row is written **only
after** the operation it's caching has already committed successfully.
This works because `IdempotentMutationMixin.post()` (Part 2) wraps
header validation, the lock on the key row, and the call into the
view's business logic inside one `transaction.atomic()` block. If the
business operation raises, the whole block rolls back — the
not-yet-committed key row rolls back with it, via the same mechanism
that already makes `StockMovementService`'s nested `atomic()` calls
behave as savepoints of one outer transaction. The practical
consequence: a row existing for `(user, key, endpoint)` is proof, by
construction, that a request with that exact body already succeeded.
Nothing needs to track "in progress."

### The DRF-specific trap this required getting right

`APIView.dispatch()` catches exceptions internally via
`self.handle_exception()` and returns a normal `Response` — the
exception never propagates out of `dispatch()`. That means relying on a
raised exception to trigger `transaction.atomic()`'s automatic rollback
only covers *some* failure paths. `VentaView`'s own seller/wrong-branch
check (§1.2) returns an explicit `403 Response` rather than raising —
confirmed by reading the existing code before writing the mixin, not
assumed. The mixin therefore checks `response.status_code >= 400`
explicitly after calling `perform_mutation()` and calls
`transaction.set_rollback(True)` itself when needed; it does not rely
on exception propagation alone.

### Why the mixin hooks `post()`, not `dispatch()`/`initial()`

Permission checks (`permission_classes`) run inside DRF's `initial()`,
which always executes before a handler method (`post()`) is called. An
unauthorized caller must get `403`, not `400` for a missing
`Idempotency-Key` — the endpoint's idempotency requirement shouldn't
leak to someone who isn't allowed to call it at all. Hooking `post()`
gets that ordering for free, without reimplementing any DRF internals:
by the time the mixin's `post()` runs, `initial()` has already
succeeded. The cost: views using this mixin implement
`perform_mutation()` instead of `post()` directly — a one-line rename,
not a redesign.

---

## Part 2 — Enforcement

### Wiring

All nine stock-mutating views (`Ingreso`, `Venta`, `Transferencia`,
`ConfirmTransfer`, `CancelTransfer`, `Ajuste`, `Devolucion`, `Donacion`,
`ReverseMovement`) now use `IdempotentMutationMixin`, with `post()`
renamed to `perform_mutation()`.

### A real drf-spectacular problem found while wiring, not anticipated in the plan

`@extend_schema` on a method only works if drf-spectacular can find it
on a method literally named after the HTTP verb (`post`). Once `post()`
is supplied by the mixin and each view defines `perform_mutation()`
instead, there's no `post()` on the concrete class for a
method-decorator to attach to — decorating `perform_mutation()` directly
would simply never be picked up, silently degrading the Swagger docs for
all nine endpoints to a generic, undocumented operation. The fix:
`@extend_schema_view(post=extend_schema(...))` at the class level, which
maps schema info to an operation name regardless of where in the MRO
that method is actually implemented. Three of the nine views
(`ConfirmTransferView`, `CancelTransferView`, `ReverseMovementView`)
already had a `409` response documented for their own business case
("transfer already confirmed", "already reversed"); since an
OpenAPI `responses` dict allows only one entry per status code, adding
`409` for idempotency conflicts there required merging both causes into
one description rather than silently overwriting the existing one.

### `BUSINESS_RULES.md` §12

Documents which endpoints require the header, the three behaviors
(replay, conflict, failed-attempt-not-cached), key scoping
`(user, key, endpoint)`, and the `IDEMPOTENCY_KEY_REQUIRED` escape hatch
— explicitly framed as an emergency lever, not a supported steady state.

### Expected fallout, by design

At the end of Part 2, roughly 40 pre-existing call sites across
`test_permissions.py`, `test_query_count.py`, `test_supplier_ingreso.py`,
and `test_reversals.py` fail with `400 idempotency_key_required`. This
was scoped and accepted in the plan, not a regression — Part 3 fixes it.

---

## Part 3 — Fallout Cleanup and Audit Trail

### Fixing the ~40 call sites

`tests/helpers.py::idempotent_post()` wraps `client.post()` with an
auto-generated UUID key per call. A per-fixture default header (e.g. via
`client.credentials(...)` in `admin_client`) was considered and
rejected: several existing tests reuse the same client for two
logically distinct write calls (create a transfer, then confirm it) —
a static default key would make those two calls collide and produce a
spurious `409`, a worse failure than the one being fixed. Two very
concrete places where distinct keys per call matter and were verified
by hand: `test_cannot_confirm_already_confirmed_transfer` and
`test_cannot_cancel_confirmed_transfer` both call `confirm`/`cancel`
twice in the same test expecting the *second* call to fail with the
real business error (`transfer_already_confirmed`) — reusing one key
across both calls would have returned `idempotency_key_conflict`
instead, the same HTTP status but the wrong reason, silently corrupting
what those tests actually verify.

### Query-count contracts

`test_venta_query_count`, `test_transferencia_create_query_count`, and
`test_transferencia_confirm_query_count` went from 3/3/4 to 6/6/7. The
idempotency layer adds, on the success path: a `SELECT ... FOR UPDATE`
that misses (no prior key), an `INSERT` creating the placeholder row,
and an `UPDATE` storing the final response — three additional queries
on every write endpoint, unavoidable given the design (the lock and the
stored response are the entire mechanism).

**These three numbers are a reasoned estimate, not a measured one.** The
environment this was developed in has no Postgres access to actually run
the suite. Each test's docstring documents the query-by-query reasoning
and is explicitly flagged for verification against a real run before
being trusted — see the ⚠️ comment in each test. `docs/phase-4.md`'s
query-count table was updated to match, cross-referenced back to this
document, since it documents these counts as architecture, not merely as
test internals.

### `cleanup_idempotency_keys`

Same cron-facing shape as `check_low_stock` (Phase 7): deletes
`IdempotencyKey` rows past `expires_at`, supports `--dry-run`.

### Audit trail — `apps/audit/`

The second, unrelated pillar of Phase 8. `AuditLog` records who changed
what on `Product`, `Branch`, and `User`.

Two design choices, both deliberate departures from Django's more
"automatic" tooling, consistent with a preference already established
elsewhere in this project (e.g. avoiding `depth=` on
`ModelSerializer.Meta`):

- **Not `django-simple-history`.** Its default user-capture middleware
  assumes session-based auth populates `request.user` before the
  middleware runs — this project authenticates via JWT inside DRF, where
  `request.user` only resolves inside a view, the same reason
  `IdempotentMutationMixin` is a DRF mixin and not a Django middleware
  (Part 1). Making the library work here requires setting
  `_history_user` manually per view anyway, at which point it's not
  saving meaningfully more work than a small purpose-built model, while
  adding a dependency whose default behavior doesn't fit this stack.
- **`(model_name, object_id)` pair instead of `GenericForeignKey`.**
  There are exactly three models being audited, known upfront — a
  `django_content_type` join for an open-ended generic reference isn't
  buying anything here.

Capture happens explicitly in `AuditedUpdateMixin.perform_update()`, the
standard DRF hook `UpdateModelMixin` provides for exactly this kind of
side effect — not via `pre_save`/`post_save` signals, which have no
reliable access to `request.user` without thread-local state (and
wouldn't work at all during `seed_dev_data`, which has no request). The
accepted trade-off: changes made via the Django admin or a shell session
aren't captured — admin/shell access already implies a different trust
boundary than API access, and what this audit trail answers is "what did
a user of the system do through the API."

`GET /api/v1/audit-log/` (admin only, filterable by `model` and
`object_id`) is the read side — an audit trail nobody can query isn't
useful.

---

## Key Technical Decisions

| Decision | Choice | Reason |
|---|---|---|
| Idempotency storage | Postgres table | Redis is out of scope by project constraint; a plain table matches everything else here |
| Where the mixin hooks in | `post()`, not `dispatch()`/`initial()` | Gets permission-before-idempotency ordering for free, no DRF internals reimplemented |
| Rollback on failure | No `status` field; failed attempts never commit a row | Simpler than a state machine, and correct by construction given the transaction boundary |
| Rollback on a returned (not raised) error | Explicit `transaction.set_rollback(True)` check | `transaction.atomic()` only auto-rolls-back on a propagated exception; `VentaView`'s own 403 doesn't raise |
| Header requirement | Mandatory, with `IDEMPOTENCY_KEY_REQUIRED` escape hatch | Optional protects nobody who doesn't already opt in; the escape hatch is operational, not architectural |
| Schema documentation for the 9 views | `@extend_schema_view` at class level | `@extend_schema` on `perform_mutation()` would be invisible to drf-spectacular |
| Query-count contract updates | Reasoned estimate, explicitly flagged | No DB access in the environment this was written in — honesty over false precision |
| Audit trail library | Custom `AuditLog`, not `django-simple-history` | Default user-capture doesn't fit JWT-inside-DRF without the same manual work a custom model needs anyway |
| Audit trail reference shape | `(model_name, object_id)`, not `GenericForeignKey` | Three known models, not an open-ended set; avoids an unnecessary join |
| Audit capture point | Explicit in `perform_update()`, not signals | Signals have no reliable `request.user` without thread-locals |

---

## Endpoints Introduced

```
GET   /api/v1/audit-log/
```

Every stock-mutating endpoint listed in `BUSINESS_RULES.md` §12.1 now
requires the `Idempotency-Key` header.

---

## Running Phase 8 Locally

```bash
make build
make up
make migrate

# Part 1 — idempotency in isolation
pytest apps/idempotency -v

# Part 2 — wiring, end-to-end
pytest apps/movements/tests/test_idempotency_wiring.py -v

# Part 3 — fallout + audit trail
pytest apps/movements/tests/test_query_count.py -v   # confirm the ⚠️ estimated counts, correct if wrong
pytest apps/audit -v
pytest apps/idempotency/tests/test_cleanup_command.py -v

# Everything
make test
```

If `test_query_count.py` fails: that confirms the estimate in this
document and in the test docstrings was wrong. Use the actual count
`django_assert_num_queries` reports, update the three assertions, and
update this document and `docs/phase-4.md` to match — don't adjust the
number blindly until it passes without reading why it changed.
