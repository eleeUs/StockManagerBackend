# Phase 7 — Valorización, Proveedores y Alertas de Stock

## Overview

Phase 7 closes the biggest gap identified after Phase 6: the system could
tell you *what* stock existed and *what happened* to it, but not *what it
was worth* or *when to reorder it*. This phase adds product pricing with
role-aware visibility, a `Supplier` domain, per-branch reorder thresholds,
an inventory valuation report, and a cron-friendly low-stock alert command.

Nothing from Phases 1–6 was rewritten. Every change here is additive —
new fields, one new app, one new report, one new management command.

---

## What Was Built

### Pricing on `Product`

`cost_price` and `sale_price` were added to `Product` as nullable
`DecimalField`s (`MinValueValidator(0)`). Nullable is a deliberate choice:
not every product has pricing loaded on day one, and the system has to stay
usable without it rather than forcing a backfill before Phase 7 can ship.

The interesting decision is **visibility, not storage**. `cost_price` is
margin-sensitive — a seller who can see acquisition cost next to sale price
can trivially compute profit margin, which isn't part of their role.
`ProductSerializer.to_representation()` strips `cost_price` for sellers:

```python
def to_representation(self, instance):
    data = super().to_representation(instance)
    request = self.context.get("request")
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_seller", False):
        data.pop("cost_price", None)
    return data
```

Doing this in `to_representation` — not a separate serializer, not a
view-level filter — means every existing call site (list, detail, and any
future nested usage) inherits the restriction automatically. `sale_price`
stays visible to both roles, since it's the number a seller actually quotes
to a customer.

### `apps/suppliers` — new app

A `Supplier` model (name, contact fields, `is_active`) with the same
list/detail CRUD shape as `Branch`: both roles can list (sellers see active
suppliers only), only admins can create or update. Suppliers are never
hard-deleted, same rationale as `Branch` and `Product` — `StockMovement`
references them and `on_delete=PROTECT` keeps that reference valid forever.

This is a full app (`apps/suppliers`), not a model bolted onto `products`,
because it's registered in `INSTALLED_APPS` and needs its own migration —
unlike `apps/reports` in Phase 6, this one has real state.

### `supplier` on `StockMovement`

An optional FK, but constrained to make sense only where it makes sense:

```python
models.CheckConstraint(
    check=(
        models.Q(supplier__isnull=True) |
        models.Q(movement_type="ingreso")
    ),
    name="movement_supplier_only_for_ingreso",
),
```

A supplier is only meaningful on an entry (`ingreso`) — no other movement
type has a concept of "where did this come from." The constraint is
DB-level, not just serializer-level, following the same philosophy already
in place for every other business rule in this codebase: the database is
the last line of defense, not the only one. `IngresoSerializer` exposes
`supplier` as optional (`required=False, allow_null=True`) — an entry
without a known supplier on file is still a valid entry.

### `reorder_point` on `Stock`

Added per `(product, branch)` row, not as a global setting. Demand for the
same product legitimately differs by branch — a single system-wide
threshold would either over-alert a busy branch or under-alert a quiet one.
`null` means *no alert configured for this row*, explicitly not "use some
fallback default."

Updating it goes through a narrow, dedicated endpoint rather than widening
`StockSerializer` into a writable one:

```
PATCH /api/v1/stock/{id}/reorder-point/
```

This is intentional: the project's existing convention is that `quantity`
is only ever reachable through `StockMovementService`, never directly from
a view. `reorder_point` is metadata, not a stock mutation, so it's safe to
expose — but the endpoint is scoped to touch *only* that field, so the
"views never touch Stock directly" boundary isn't quietly widened by a
generic update endpoint that happens to also allow `reorder_point`.

### Low-stock alerts — `check_low_stock`

```bash
python manage.py check_low_stock
python manage.py check_low_stock --webhook-url https://hooks.example.com/low-stock
```

Scans `Stock` rows where `reorder_point` is set and `quantity <=
reorder_point`, logs each one, and prints a summary. The `--webhook-url`
flag POSTs a JSON payload using `urllib.request` from the standard library —
no new dependency was added for this, since the project's constraint set
already rules out Celery/async task queues (see `phase6_prompt.md`). This
is designed to be invoked externally on a schedule (cron, a Kubernetes
`CronJob`), not as a background task the app manages itself.

### Inventory valuation report

```
GET /api/v1/reports/stock/valuation/?branch=2
```

Admin only, for the same reason `cost_price` itself is admin-only. Computed
as `quantity × cost_price`, aggregated by branch and by product via
`ExpressionWrapper` + `Sum` at the database level — no Python-side looping
over rows.

Stock rows for products with no `cost_price` are **excluded** from the
total, not treated as worth zero. The response includes
`products_missing_cost_price` so an admin looking at the total valuation
knows immediately whether the number is complete or partial, instead of
silently trusting an understated figure.

---

## Key Technical Decisions

| Decision | Choice | Reason |
|---|---|---|
| `cost_price`/`sale_price` nullability | Nullable | System must stay usable before every product has pricing loaded |
| `cost_price` visibility | Stripped in `to_representation()` for sellers | Margin-sensitive; applies automatically everywhere the serializer is used |
| Suppliers | Full app (`apps/suppliers`), not a field on `products` | Has real state and its own migration, unlike the models-less `apps/reports` |
| `supplier` on movements | Optional FK + DB `CheckConstraint` restricting it to `ingreso` | Matches the project's existing "constraint is the last line of defense" philosophy |
| `reorder_point` scope | Per `(product, branch)` row, not global | Demand differs by branch; a single threshold either over- or under-alerts |
| `reorder_point` update path | Dedicated endpoint, narrow serializer | Keeps `quantity` reachable only via `StockMovementService`; doesn't widen that boundary |
| Low-stock alerting | Management command + optional webhook via stdlib `urllib` | No task queue in this project by design; no new dependency needed for a simple POST |
| Valuation exclusions | Skip unpriced rows, report the count | Never silently understate a financial total |

---

## Endpoints Introduced

```
GET    /api/v1/suppliers/
POST   /api/v1/suppliers/
GET    /api/v1/suppliers/{id}/
PATCH  /api/v1/suppliers/{id}/

PATCH  /api/v1/stock/{id}/reorder-point/

GET    /api/v1/reports/stock/valuation/
```

`POST /api/v1/movements/ingreso/` now additionally accepts an optional
`supplier` field.

---

## A Bug Fixed Along the Way

While extending `apps/movements/tests/test_services.py`'s ingreso tests for
context, `test_ingreso_adds_to_existing_stock` referenced an undefined
`make_stock(...)` helper — a leftover from the Phase 4 factory_boy refactor
that removed the manual helper functions but missed this one call site.
Fixed by replacing it with `StockFactory(...)`, which was already imported
in that file. Everything else in Phases 1–6 was left untouched.

---

## Running Phase 7 Locally

```bash
make build
make up
make migrate

# Reseed with the new pricing/supplier data (safe to re-run, get_or_create throughout)
make seed

# Phase 7 tests
docker-compose exec api pytest apps/suppliers apps/stock/tests apps/products/tests \
    apps/movements/tests/test_supplier_ingreso.py \
    apps/reports/tests/test_reports.py::TestStockValuationReport -v

# Low-stock check (won't find anything until a reorder_point is set)
docker-compose exec api python manage.py check_low_stock

# Full suite
make test
```
