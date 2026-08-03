# Business Rules — Multi-Branch Stock Management System

> **Status:** Approved
> **Last updated:** 2026-08-01 (Phase 7 — pricing, suppliers, reorder alerts)
> **Scope:** Backend API — Django + PostgreSQL

---

## 1. User Roles and Permissions

### 1.1 Roles

There are exactly two roles in the system: **Admin** and **Seller**.

### 1.2 Seller

- A seller is always assigned to exactly one branch. This assignment is mandatory; a seller cannot exist in the system without a branch.
- A seller can perform **sales only within their assigned branch**. They cannot sell on behalf of another branch.
- A seller can **read the current stock level of any branch** (read-only, no write access to other branches).
- A seller cannot perform transfers, stock entries, adjustments, returns, or donations.
- A seller cannot create, edit, or deactivate users.

### 1.3 Admin

- An admin is not bound to any specific branch and can operate across all branches.
- An admin can perform all movement types: sale, entry, transfer, adjustment, return, and donation.
- An admin can create, edit, and deactivate users.
- An admin can assign or reassign sellers to branches.
- An admin can create and manage branches, products, and suppliers.

---

## 2. Stock Rules

### 2.1 Non-negativity

- **Stock can never go below zero.** This rule is enforced at the database level via a `CHECK` constraint and at the application level in every service that modifies stock.
- Any operation that would result in negative stock must be **rejected immediately** with a clear error response before any write is committed.
- There are no exceptions to this rule, regardless of user role.

### 2.2 Stock Snapshot vs. Movement History

- The system maintains two separate records:
  - A **Stock table** (`Stock`): holds the current quantity per product per branch. This is the source of truth for "what is available right now."
  - A **Movement table** (`StockMovement`): holds the immutable historical log of every change. This is the source of truth for "what happened and when."
- These two must always be in sync. Any operation that updates stock **must** create a corresponding movement record within the same database transaction.

### 2.3 Stock Visibility

- Any authenticated user (admin or seller) can query the current stock level of any branch.
- Write operations on stock are restricted by role as defined in section 1.

---

## 3. Movement Types

### 3.1 Entry (`ingreso`)

- **Who:** Admin only.
- **Effect:** Increases stock at the destination branch.
- **Required fields:** product, destination branch, quantity (> 0), formal entry date, notes (optional).
- **Optional field:** supplier — see §10. Not every entry has a supplier on file; the field exists for traceability, not as a hard requirement.
- **Rule:** An entry must always be registered with a formal date and the destination branch. Stock cannot be increased arbitrarily without a corresponding entry record.
- Source branch: none.

### 3.2 Sale (`venta`)

- **Who:** Admin or Seller.
- **Seller restriction:** Can only sell from their assigned branch.
- **Effect:** Decreases stock at the source branch.
- **Required fields:** product, source branch, quantity (> 0).
- **Rule:** A sale cannot be processed if the current stock at the source branch is insufficient. The system must validate stock availability before committing the transaction.
- Destination branch: none.

### 3.3 Transfer (`transferencia`)

- **Who:** Admin only.
- **Effect:** Decreases stock at the source branch and increases stock at the destination branch.
- **Required fields:** product, source branch, destination branch, quantity (> 0).
- **Rule:** Source branch and destination branch must be different.
- **Rule:** Transfers follow a **two-step confirmation flow**:
  1. **Pending (`pending`):** The transfer is created. Stock at the source branch is reserved (decremented) immediately upon creation, to prevent the reserved quantity from being sold or moved elsewhere.
  2. **Confirmed (`confirmed`):** The admin explicitly confirms the transfer. Stock at the destination branch is incremented at this point.
  - A pending transfer can be **cancelled (`cancelled`)** before confirmation. Cancellation must restore the reserved quantity to the source branch.
  - A confirmed transfer cannot be cancelled. A reversal movement must be created instead (see section 5).
- Pending transfers must be clearly visible in the system and distinguishable from confirmed ones.

### 3.4 Adjustment (`ajuste`)

- **Who:** Admin only.
- **Effect:** Sets or modifies the stock at a given branch. Can increase or decrease the quantity, including setting it to exactly zero.
- **Required fields:** product, branch, new quantity or delta, reason/notes.
- **Rule:** An adjustment can bring stock to zero but never below zero.
- **Rule:** An adjustment that increases stock is not a substitute for a formal Entry. If the intent is to record new incoming goods, an Entry must be used. Adjustments are intended for inventory corrections (e.g., after a physical count).
- Source and destination semantics do not apply; the adjustment references a single branch.

### 3.5 Return (`devolucion`)

- **Who:** Admin only.
- **Effect:** Increases stock at the branch where the original sale took place.
- **Required fields:** product, branch (must be the same branch where the sale occurred), quantity (> 0), reference to the original sale movement (optional but strongly recommended).
- **Rule:** A return always goes back to the **same branch** where the product was originally sold. Returns to a different branch are not allowed.
- **Rule:** A return cannot exceed the original sold quantity. If partial returns are tracked, the cumulative returned quantity for a given sale must not exceed the sold quantity.
- Destination branch: same as original sale branch. Source branch: none.

### 3.6 Donation (`donacion`)

- **Who:** Admin only.
- **Effect:** Decreases stock at the source branch.
- **Required fields:** product, source branch, quantity (> 0), notes (optional).
- **Rule:** A donation cannot be processed if the current stock at the source branch is insufficient.
- Destination branch: none (external recipient).

---

## 4. Movement Status Flow

```
[Transfer only]

  PENDING ──── confirmed by admin ────► CONFIRMED
     │
     └────── cancelled by admin ──────► CANCELLED

[All other movement types]

  Created ──────────────────────────── CONFIRMED (immediate, single-step)
```

All non-transfer movements are single-step and are created in a confirmed state directly.

---

## 5. Immutability and Reversals

- **No movement record is ever edited or deleted** once created.
- If a confirmed movement must be corrected, a **reversal movement** is created. The reversal:
  - References the original movement via a `reverses_movement` field.
  - Has the opposite stock effect of the original.
  - Is only allowed for admin users.
- The Stock snapshot is updated at the time the reversal is created, within the same transaction.
- Pending transfers are cancelled (not reversed), and the cancellation restores the source stock.

---

## 6. Concurrency and Data Integrity

- All operations that read and then write stock quantities must use **row-level locking** (`SELECT FOR UPDATE`) within a database transaction (`ATOMIC`).
- For transfers involving two branches, locks must always be acquired in a **consistent order** (e.g., ascending branch ID) to prevent deadlocks under concurrent load.
- The database-level `CHECK` constraint on stock quantity is the last line of defense and must never be the only line of defense. Application-level validation must occur first.

---

## 7. Audit Trail

- Every movement record stores:
  - The user who created it (`created_by`).
  - The exact timestamp of creation (`created_at`).
  - The movement type, product, branch(es), and quantity.
- This audit trail is permanent and cannot be altered.
- Admins can query the full movement history filtered by date range, branch, product, movement type, and user.
- Sellers can query the movement history of their own branch only.

---

## 8. Constraints Summary Table

| Operation | Min stock required | Stock after | Two-step | Who |
|---|---|---|---|---|
| Entry | No | + destination | No | Admin |
| Sale | Yes (> 0) | − source | No | Admin, Seller |
| Transfer | Yes (> 0 at source) | − source / + dest | **Yes** | Admin |
| Adjustment | No (can go to 0) | = new value | No | Admin |
| Return | No | + branch of sale | No | Admin |
| Donation | Yes (> 0) | − source | No | Admin |

---

## 9. Pricing and Inventory Valuation *(Phase 7)*

### 9.1 Product pricing

- A product may have two independent price fields: `cost_price` (unit acquisition cost) and `sale_price` (unit sale price to customers). Both are optional — not every product has pricing loaded on day one, and the system must remain usable without it.
- Only admins can set or edit `cost_price` and `sale_price`, via the same product create/update endpoints used for the rest of the catalog.
- Neither price field affects stock movement logic. Pricing is informational and reporting data; it has no bearing on `venta`, `ingreso`, or any other movement's validation rules.

### 9.2 Cost price visibility

- **`cost_price` is visible to admins only.** A seller who can see acquisition cost next to sale price can directly infer profit margin, which is not part of their role.
- **`sale_price` is visible to both admins and sellers** — it's the number the seller actually quotes to a customer.
- This restriction applies everywhere a product is serialized (list, detail), not only on a single endpoint.

### 9.3 Inventory valuation

- Inventory valuation is computed as `quantity × cost_price`, summed per branch and per product.
- Stock rows for products with no `cost_price` set are **excluded** from the valuation total — they are never silently treated as worth zero. The valuation report surfaces a count of products missing cost data so the total's completeness is never ambiguous.
- Valuation reporting is admin-only, for the same reason `cost_price` itself is admin-only.

---

## 10. Suppliers *(Phase 7)*

- A `Supplier` represents an external party that stock is formally received from.
- Suppliers are managed exclusively by admins (create, edit). Both roles can list suppliers for reference; sellers only see active suppliers.
- Suppliers are never hard-deleted — deactivate via `is_active=False`, the same policy as `Branch` and `Product`. Movement history references suppliers and must remain valid indefinitely.
- **A supplier can only be attached to an Entry (`ingreso`) movement.** It is optional even there — an entry without a known supplier on file is still valid. No other movement type may reference a supplier; this is enforced at the database level via a `CHECK` constraint (`movement_supplier_only_for_ingreso`), not only in application code.

---

## 11. Reorder Points and Low-Stock Alerts *(Phase 7)*

- Each `Stock` row (i.e. each product-branch combination) may have its own `reorder_point`. This is deliberately **not** a global default — demand for the same product legitimately differs by branch, and a single system-wide threshold would either over-alert busy branches or under-alert quiet ones.
- `reorder_point = null` means **no alert is configured for that row**, not "use some fallback threshold." Rows with no reorder point configured are never included in a low-stock alert.
- Only admins can set or clear a row's `reorder_point`, via a dedicated endpoint that touches only that field — never `quantity`, which remains reachable exclusively through the movement service layer.
- Low-stock evaluation (`quantity <= reorder_point`) is expected to run on a schedule external to the request/response cycle (cron, a scheduled job) rather than being computed synchronously on every stock read, since the project intentionally has no background task queue (see `phase6_prompt.md`).
