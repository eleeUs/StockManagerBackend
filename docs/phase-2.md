# Phase 2 — Stock Models and Service Layer

## Overview

Phase 2 builds the core of the system: the `Stock` snapshot model, the
append-only `StockMovement` ledger, and the service layer that is the single
point of truth for all stock mutations.

The central challenge of this phase is **concurrency**: multiple users at
different branches can trigger simultaneous operations on the same stock row.
Without row-level locking, two sales of the last unit produce negative stock.

---

## What Was Built

### `Stock` model (`apps/stock`)

The `Stock` model holds the **current** quantity for a given `(product, branch)`
pair. It answers the question *"what is available right now?"*

```python
class Stock(models.Model):
    product  = ForeignKey(Product, on_delete=PROTECT)
    branch   = ForeignKey(Branch,  on_delete=PROTECT)
    quantity = DecimalField(max_digits=12, decimal_places=3, default=0)

    class Meta:
        unique_together = [("product", "branch")]
        constraints = [
            CheckConstraint(
                check=Q(quantity__gte=0),
                name="stock_quantity_non_negative",
            )
        ]
```

`DecimalField` is used instead of `IntegerField` to support both
whole-unit products and weight-based products (kg, g) defined by
`Product.unit_type`. `FloatField` is explicitly avoided — floating-point
arithmetic produces rounding errors that accumulate over thousands of
operations.

The `CheckConstraint` is a database-level guard. The service layer
raises `InsufficientStockError` before any write attempt, but the
constraint is the last line of defence against bugs in the service
or direct database access.

### `StockMovement` model (`apps/movements`)

The `StockMovement` model is the **historical ledger**. It answers the question
*"what happened and when?"*

Key design rules:
- Records are **never edited or deleted**. Corrections are made by creating
  a new reversal movement that references the original via `reverses_movement`.
- `quantity` is always positive. The stock effect (add vs subtract) is
  determined by `movement_type` and which branch field is populated.
- `source_branch` and `destination_branch` are both nullable because not all
  movement types use both.

**Source / destination matrix:**

| Type | source_branch | destination_branch |
|---|---|---|
| `ingreso` | — | branch receiving stock |
| `venta` | branch selling stock | — |
| `transferencia` | origin branch | destination branch |
| `ajuste` | — | adjusted branch |
| `devolucion` | — | branch where sale occurred |
| `donacion` | branch donating stock | — |

**Five database constraints enforce business rules at the storage level:**
1. `movement_quantity_positive` — quantity > 0 always.
2. `stock_quantity_non_negative` — stock can never go below zero.
3. `movement_pending_cancelled_only_for_transfers` — only transfers have
   pending/cancelled status; all other types are confirmed immediately.
4. `movement_source_dest_different` — a transfer cannot have the same
   source and destination.

**Five indexes are defined** on the most common filter combinations
(product+date, source_branch+date, destination_branch+date, type+date,
status+type) to prevent full table scans on the history endpoint.

### Service layer (`apps/movements/services.py`)

The service layer is the **only** place where stock mutation logic lives.
Views and serializers call service methods; they never touch `Stock` directly.

#### Concurrency strategy

Every write operation follows this pattern:

```python
with transaction.atomic():
    stock = Stock.objects.select_for_update().get(
        product_id=product_id,
        branch_id=branch_id,
    )
    # validate → mutate → save → create movement record
```

`select_for_update()` acquires a **row-level lock** on the stock row. Any
concurrent transaction attempting to lock the same row waits until the first
transaction commits or rolls back. This serializes concurrent writes to the
same `(product, branch)` stock at the database level.

#### Deadlock prevention for transfers

A transfer locks two stock rows. If two cross-transfers occur simultaneously
without ordering:

```
T1: locks branch 1, waits for branch 2
T2: locks branch 2, waits for branch 1  ← deadlock
```

The solution: always acquire locks in **ascending `branch_id` order**.

```python
id_low, id_high = sorted([source_branch_id, destination_branch_id])
stocks = Stock.objects.select_for_update().filter(
    product_id=product_id,
    branch_id__in=[id_low, id_high],
)
```

Both transactions now attempt to lock the lower-ID branch first.
One waits; no deadlock.

#### Two-step transfer flow

Transfers are created with `status=PENDING`. The source stock is
**decremented immediately on creation** to reserve the quantity — preventing
it from being sold or moved while the transfer is in transit.

On confirmation, destination stock is incremented and status becomes
`CONFIRMED`. On cancellation, source stock is restored and status becomes
`CANCELLED`. A confirmed transfer cannot be cancelled; it must be reversed.

#### `get_or_create` + `select_for_update` pattern

For operations that may be the first movement for a `(product, branch)` pair
(ingreso, devolucion), `get_or_create` is called first to ensure the row
exists, then `select_for_update` locks it. This handles the race condition
where two concurrent ingresos both find no row and both try to insert one:
Django catches the `IntegrityError` from the second insert and retries the
`get`, ensuring exactly one row is ever created.

---

## Key Technical Decisions

| Decision | Choice | Reason |
|---|---|---|
| Two tables (Stock + StockMovement) | Snapshot + ledger | Avoid recalculating sums for current stock on every query |
| `DecimalField` for quantity | Not `IntegerField` or `FloatField` | Supports weight products; avoids floating-point drift |
| Row-level locking | `select_for_update()` | Prevents race conditions under concurrent load |
| Lock ordering | Ascending `branch_id` | Prevents deadlocks on cross-branch transfers |
| Transfer status | Three-state: pending/confirmed/cancelled | Source is reserved immediately; destination only updated on confirm |
| Movement immutability | No UPDATE or DELETE | Full audit trail; corrections via reversal records |

---

## Endpoints Introduced

```
GET    /api/v1/stock/
GET    /api/v1/stock/product/{id}/by-branch/
GET    /api/v1/movements/
POST   /api/v1/movements/ingreso/
POST   /api/v1/movements/venta/
POST   /api/v1/movements/transferencia/
POST   /api/v1/movements/transferencia/{id}/confirm/
POST   /api/v1/movements/transferencia/{id}/cancel/
POST   /api/v1/movements/ajuste/
POST   /api/v1/movements/devolucion/
POST   /api/v1/movements/donacion/
```

---

## Running the Concurrency Tests

```bash
# These use TransactionTestCase with real threads — they require a live DB
docker-compose exec api pytest apps/movements/tests/test_services.py -v -k "concurrent"
```
