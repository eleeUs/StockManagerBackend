# Phase 3 — Testing Infrastructure, Scoping, and API Documentation

## Overview

Phase 3 introduces the testing infrastructure that makes the permission model
verifiable, the `BranchScopeQuerysetMixin` that centralizes branch filtering as
a security policy, cursor pagination with a stable compound ordering key, and
`@extend_schema` annotations on all `APIView` endpoints that `drf-spectacular`
cannot auto-document.

---

## What Was Built

### Testing infrastructure (`tests/factories.py` + `conftest.py`)

#### Why factory_boy instead of raw ORM calls

Permission tests require many combinations of users, branches, and stock states.
Writing `Branch.objects.create(...)`, `Product.objects.create(...)`,
`User.objects.create_user(...)` in every `setUp` produces test files where setup
code outnumbers assertion code. `factory_boy` eliminates this.

```python
# Before (manual setup)
def setUp(self):
    self.branch  = Branch.objects.create(name="Branch A", address="...")
    self.product = Product.objects.create(sku="P1", name="P1", unit_type="unit")
    self.seller  = User.objects.create_user(
        email="s@test.com", role="seller", branch=self.branch, ...
    )

# After (factories)
def setUp(self):
    self.branch  = BranchFactory()
    self.product = ProductFactory()
    self.seller  = SellerFactory(branch=self.branch)
```

`SubFactory` resolves dependencies automatically. `SellerFactory` creates a
`BranchFactory()` internally if no branch is provided.

#### Factory hierarchy

```
UserFactory (base, role=seller)
├── AdminFactory   (role=admin, branch=None)
└── SellerFactory  (role=seller, branch=SubFactory(BranchFactory))

ProductFactory (unit_type=unit)
└── WeightProductFactory (unit_type=weight)

StockMovementFactory
└── PendingTransferFactory (status=pending, movement_type=transferencia)
```

`StockMovementFactory` is only used for **read** tests (filtering, history,
pagination). Write tests always go through `StockMovementService` so the
`Stock` snapshot stays in sync with the movement record.

#### Fixtures (`conftest.py`)

Root-level `conftest.py` provides fixtures available to all test modules:

- `api_client` — unauthenticated `APIClient`. Used for 401 tests.
- `admin_client` — returns `(client, user)`. Admin pre-authenticated.
- `seller_client` — returns `(client, user, branch)`. Seller pre-authenticated
  with their branch.
- `product_with_stock` — returns `(product, branch, stock)` with 50 units.
- `two_branches_with_stock` — returns `(product, branch_a, branch_b)` with
  30 units at each. Used for transfer tests.

The tuple pattern (`client, user, branch = seller_client`) keeps related objects
together without requiring multiple separate fixtures that must coordinate.

### `BranchScopeQuerysetMixin` (`core/mixins.py`)

Branch filtering is a security policy. Security policies must live in one place
and be explicit.

```python
class BranchScopeQuerysetMixin:
    branch_field = "branch"

    def get_branch_q(self, user) -> Q:
        return Q(**{self.branch_field: user.branch})

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_seller:
            qs = qs.filter(self.get_branch_q(user))
        return qs
```

The template method pattern (`get_branch_q`) allows subclasses to override
just the filter logic when the default single-field filter is insufficient.
`MovementListView` overrides it for the OR condition:

```python
def get_branch_q(self, user) -> Q:
    return (
        Q(source_branch=user.branch) |
        Q(destination_branch=user.branch)
    )
```

Sellers see both outgoing and incoming movements for their branch. A seller
must be able to see when an inbound transfer arrives, not just when they sold.

`StockListView` intentionally bypasses the mixin for sellers because
`BUSINESS_RULES §1.2` grants sellers global **read** visibility on stock.
The write restriction is enforced at the movement creation level, not the stock
read level. This is documented explicitly in the view.

### Cursor pagination compound ordering (`core/pagination.py`)

```python
class MovementCursorPagination(CursorPagination):
    ordering = ("-created_at", "id")
```

Using only `created_at` is unstable: two movements created in the same
microsecond under concurrent load produce a non-unique cursor position —
a record may appear on two pages or be skipped entirely.

`id` is strictly monotonic in PostgreSQL (sequences never repeat). The
compound `(created_at DESC, id ASC)` is always unique. `drf-spectacular`
exposes `created_at` in the cursor as the temporal anchor, which is also
useful for debugging pagination issues in production.

`CursorPagination` is used instead of `PageNumberPagination` for the movement
history because it does not issue a `COUNT(*)` query and uses a `WHERE` clause
on an indexed column. `OFFSET N` degrades linearly as the table grows; a
cursor-based `WHERE` clause is `O(log N)` regardless of table size.

### OpenAPI annotations (`@extend_schema`)

`drf-spectacular` auto-generates correct schemas for `GenericAPIView` and
`ModelViewSet` by inspecting the declared serializer class. It cannot infer
schemas for `APIView` subclasses where the serializer is instantiated inside
`post()` rather than declared on the class.

`@extend_schema` is applied to every `APIView` endpoint with:
- `request=` — the input serializer, so clients know the request body shape.
- `responses=` — one entry per possible HTTP status with a description.
- `summary=` — one line for the Swagger UI endpoint list.
- `tags=` — groups related endpoints in the Swagger UI sidebar.

Shared `OpenApiResponse` objects (`_INSUFFICIENT_STOCK`, `_INVALID_MOVEMENT`,
etc.) are defined once and reused across views to avoid description drift.

### Permission tests (`test_permissions.py`)

Each test class maps to a section of `BUSINESS_RULES.md`. Each test method
maps to a single rule. The docstring cites the section reference.

```python
def test_seller_cannot_sell_from_other_branch(self, seller_client, product):
    """BUSINESS_RULES §1.2: seller is restricted to their assigned branch."""
```

`TestUnauthenticated` uses `@pytest.mark.parametrize` to verify all 9 critical
endpoints return 401 with a single test block — adding a new endpoint to the
list is one line.

---

## Key Technical Decisions

| Decision | Choice | Reason |
|---|---|---|
| Test data | `factory_boy` | Readable setup, dependency resolution, consistent style |
| Fixtures | Tuple returns `(client, user, branch)` | Avoids fixture coordination overhead |
| Branch filtering | `BranchScopeQuerysetMixin` with `get_branch_q` | Security policy in one place; extensible via override |
| Stock read for sellers | No branch filter | `BUSINESS_RULES §1.2`: sellers have global read visibility |
| Cursor ordering | `("-created_at", "id")` | Stable under concurrent inserts |
| OpenAPI coverage | `@extend_schema` on `APIView` only | `GenericAPIView` already auto-documented correctly |

---

## Running the Permission Tests

```bash
docker-compose exec api pytest apps/movements/tests/test_permissions.py -v
```
