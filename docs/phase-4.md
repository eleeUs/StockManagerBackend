# Phase 4 — Reversal System, N+1 Audit, and Test Consistency

## Overview

Phase 4 completes three outstanding items: the reversal system required by
`BUSINESS_RULES §5` (confirmed movements can be corrected but never edited),
performance contracts via query-count tests that prevent N+1 regressions, and
a selective refactor of `test_services.py` to align with the factory_boy
style established in Phase 3.

---

## What Was Built

### Reversal system

#### Model change

A new `MovementType.REVERSAL` value is added. Reversal movements are created
exclusively by the service — no client can post `movement_type: "reversal"`
directly. This is enforced at the view level by using dedicated serializers
for each movement type that do not expose a `movement_type` field.

#### Strategy pattern in `StockMovementService.revertir()`

A monolithic `if/elif` over all movement types would work, but adding a new
movement type in the future requires modifying the dispatcher rather than
registering a new function. The strategy pattern separates these concerns:

```python
_REVERSAL_STRATEGIES = {
    MovementType.INGRESO:       _reverse_ingreso,
    MovementType.VENTA:         _reverse_venta,
    MovementType.TRANSFERENCIA: _reverse_transferencia,
    MovementType.AJUSTE:        _reverse_ajuste,
    MovementType.DEVOLUCION:    _reverse_devolucion,
    MovementType.DONACION:      _reverse_donacion,
}
```

The dispatcher `revertir()` applies four guards before calling any strategy,
ordered by ascending computational cost (cheapest first):

1. Pending transfers → raise (use cancel endpoint instead).
2. Non-confirmed movements → raise.
3. Reversal of a reversal → raise (no infinite chains).
4. Already reversed → raise (DB `OneToOneField` also enforces this, but an
   explicit check surfaces a clear error message before hitting the constraint).

#### Stock effect per type

| Original type | Reversal effect |
|---|---|
| `ingreso` | `destination_branch -= quantity` |
| `venta` | `source_branch += quantity` |
| `transferencia` (confirmed) | `destination -= quantity`, `source += quantity` |
| `ajuste` | `branch.quantity = adjustment_previous_quantity` |
| `devolucion` | `destination_branch -= quantity` |
| `donacion` | `source_branch += quantity` |

Transfer reversals acquire locks in the same ascending `branch_id` order as
the original transfer service to prevent deadlocks.

#### Adjustment reversal edge case

The `quantity` field on `StockMovement` has a `MinValueValidator(Decimal("0.001"))`.
For adjustment reversals where the previous quantity was zero, the delta would
be zero — violating the constraint. The reversal stores `Decimal("0.001")` in
the `quantity` field for this edge case; the real information is preserved in
`adjustment_previous_quantity`. This is documented in the code.

#### Immutability guarantee

The original movement record is never touched. The reversal creates a new
`StockMovement` with:
- `movement_type = "reversal"`
- `reverses_movement = <original>`
- `status = "confirmed"`
- Stock effect opposite to the original

The `OneToOneField` on `reverses_movement` enforces at the database level that
each movement can be reversed at most once.

### N+1 query count audit (`test_query_count.py`)

Query counts are made into explicit, version-controlled assertions using
`django_assert_num_queries` (provided by `pytest-django`).

```python
with django_assert_num_queries(1):
    response = client.get("/api/v1/movements/")
```

Each test documents inline the expected count and the reason for each query:

```python
"""
Expected queries:
  1. SELECT movements with select_related(...) — one JOIN, all data.
CursorPagination does NOT issue a COUNT query.
"""
```

**Why this over manual silk inspection:**
Manual profiling with `django-silk` does not survive refactoring. Someone
removing a `select_related` six weeks later will not remember to check the
silk panel. A failing test is immediate and mandatory.

**What is covered:**

| Endpoint | Expected queries | Notes |
|---|---|---|
| `GET /movements/` (admin) | 1 | `select_related` fetches all in one JOIN |
| `GET /movements/` (seller) | 1 | Branch scope filter is in the same query |
| `GET /stock/` | 2 | Data + COUNT (uses `StandardPagination`) |
| `POST /movements/venta/` | 3 → **6** *(Phase 8)* | lock stock + update stock + insert movement, **+3 for idempotency**: lock/insert the key row before, update it with the response after — see `docs/phase8_prompt.md` Part 3 |
| `POST /movements/transferencia/` | 3 → **6** *(Phase 8)* | lock source + update source + insert pending, **+3 for idempotency** (same breakdown as above) |
| `POST /movements/transferencia/{id}/confirm/` | 4 → **7** *(Phase 8)* | lock movement + get_or_create dest + update dest + update status, **+3 for idempotency** (same breakdown as above) |
| `GET /products/` | 2 | Data + COUNT |

### Selective test refactor (`test_services.py`)

Only the `setUp` methods are changed. Assertions are left untouched.

```python
# Before
def setUp(self):
    self.admin   = make_admin()
    self.branch  = make_branch("Branch A")
    self.product = make_product(sku="SKU001")

# After
def setUp(self):
    self.admin   = AdminFactory()
    self.branch  = BranchFactory()
    self.product = ProductFactory()
```

The manual helper functions (`make_admin`, `make_branch`, `make_product`,
`make_stock`) are removed entirely. The factories are imported from
`tests/factories.py`, the single source of test data for the project.

---

## Key Technical Decisions

| Decision | Choice | Reason |
|---|---|---|
| Reversal endpoint | Single `POST /movements/{id}/reverse/` | Simple URL; strategy handles type-specific logic |
| Dispatcher pattern | Dict of strategies | Extensible without modifying the dispatcher |
| Guards order | Cheapest check first | Fail fast without unnecessary DB queries |
| Query count assertions | `django_assert_num_queries` | Regressions caught at CI time, not by memory |
| Test refactor scope | `setUp` only | Unify style with minimal diff; no risk to assertion logic |

---

## Endpoint Introduced

```
POST   /api/v1/movements/{id}/reverse/
```

Admin only. Returns the created reversal movement with HTTP 201.

---

## Running Phase 4 Tests

```bash
# Reversal tests
docker-compose exec api pytest apps/movements/tests/test_reversals.py -v

# Query count audit
docker-compose exec api pytest apps/movements/tests/test_query_count.py -v

# Full suite
docker-compose exec api pytest --tb=short -q
```
