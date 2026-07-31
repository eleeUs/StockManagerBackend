# Conventional Commits — Stock Management Backend

One commit per logical unit of work. Each commit is self-contained:
the codebase builds and all tests pass at every commit.

---

## Phase 1 — Project Foundation

```
chore: initialize Django project with multi-environment settings and Docker

- Split settings into base/development/production
- Configure django-environ for .env-based secrets
- Add Dockerfile and docker-compose with PostgreSQL 16 and healthcheck
- Add requirements split: base / development / production
- Add .env.example and .gitignore
```

```
feat(users): add custom AbstractBaseUser model with email authentication

- Replace default username-based User with email as USERNAME_FIELD
- Add Role field (admin/seller) with TextChoices
- Add branch FK nullable for admins, required for sellers
- Add DB-level CheckConstraint enforcing role-branch integrity
- Add UserManager with create_user and create_superuser
- Set AUTH_USER_MODEL before first migration
```

```
feat(auth): configure JWT authentication with token blacklist on logout

- Add djangorestframework-simplejwt with token_blacklist app
- Set ACCESS_TOKEN_LIFETIME to 8h, REFRESH_TOKEN_LIFETIME to 7 days
- Enable ROTATE_REFRESH_TOKENS and BLACKLIST_AFTER_ROTATION
- Add /auth/login/, /auth/refresh/, /auth/logout/, /auth/me/ endpoints
- Logout blacklists the refresh token making it immediately invalid
```

```
feat(core): add domain exception handler and custom permission classes

- Add StockDomainError hierarchy: InsufficientStockError, InvalidMovementError,
  UnauthorizedMovementError, TransferAlreadyConfirmedError
- Add custom_exception_handler mapping domain exceptions to structured HTTP responses
  with machine-readable "error" codes and human-readable "detail" fields
- Add IsAdmin, IsSeller, IsAdminOrSeller, CanAccessBranch permission classes
- Register exception handler in REST_FRAMEWORK settings
```

```
feat(branches): add Branch model with soft-delete and CRUD endpoints

- Add Branch model with name, address, is_active fields
- Soft-delete only: is_active=False instead of hard delete
- on_delete=PROTECT on all FKs to Branch to prevent accidental data loss
- Admins see all branches; sellers see only active branches
- GET is open to all authenticated users; POST/PATCH restricted to admins
```

```
feat(products): add Product and Category models with unit_type support

- Add Category model as separate table (allows rename without bulk update)
- Add Product with sku (unique, normalized to uppercase), name, category,
  unit_type (unit/weight), description, is_active
- unit_type used by service layer to validate integer-only quantities
- SKU normalized to uppercase in serializer.validate_sku
- Soft-delete only via is_active; on_delete=PROTECT on all FKs
```

---

## Phase 2 — Stock Models and Service Layer

```
feat(stock): add Stock snapshot model with non-negativity DB constraint

- One row per (product, branch) pair enforced by unique_together
- DecimalField(max_digits=12, decimal_places=3) for unit and weight products
- DB-level CheckConstraint: quantity >= 0 at all times
- Compound indexes on (branch, product) and (product, branch)
- Rows are never deleted; zero quantity is the floor
```

```
feat(movements): add append-only StockMovement ledger with audit indexes

- Add MovementType choices: ingreso, venta, transferencia, ajuste,
  devolucion, donacion
- Add MovementStatus choices: confirmed, pending, cancelled
- Nullable source_branch and destination_branch per movement type matrix
- adjustment_previous_quantity field for full audit on ajuste movements
- entry_date field for formal ingreso date (may differ from created_at)
- reverses_movement OneToOneField for linking reversals to originals
- Five DB-level CheckConstraints enforcing business rules at storage level
- Five indexes on most common filter combinations for history queries
```

```
feat(movements): implement StockMovementService with select_for_update locking

- Add service layer as single point of stock mutation logic
- All write operations use select_for_update() inside transaction.atomic()
- Add ingreso, venta, ajuste, devolucion, donacion service methods
- get_or_create + select_for_update pattern for first-time stock rows
- Validate quantity > 0 and unit products receive whole numbers
- Log all mutations with product, branch, quantity, and user
```

```
feat(movements): add two-step transfer flow with deadlock prevention

- crear_transferencia: decrements source stock immediately (reservation),
  creates movement with status=PENDING
- confirmar_transferencia: increments destination stock, sets CONFIRMED
- cancelar_transferencia: restores source stock, sets CANCELLED
- Lock two stock rows in ascending branch_id order to prevent deadlocks
  on simultaneous cross-branch transfers
- Cancellation blocked on confirmed transfers (must use reversal instead)
```

```
test(movements): add concurrent sale and transfer tests with real threads

- TestConcurrentVenta: two simultaneous sales of last unit, only one succeeds
- TestConcurrentTransfer: cross-transfers A→B and B→A simultaneously,
  no deadlock, stock totals consistent
- TransactionTestCase required for real DB transactions across threads
```

---

## Phase 3 — Testing Infrastructure, Scoping, and API Documentation

```
test: add factory_boy factories and pytest root fixtures

- Add tests/factories.py as single source of test data for the project
- BranchFactory, CategoryFactory, ProductFactory, WeightProductFactory
- UserFactory base with AdminFactory and SellerFactory subclasses
- StockFactory, StockMovementFactory, PendingTransferFactory
- Add conftest.py with api_client, admin_client, seller_client fixtures
- Tuple fixtures (client, user, branch) for coordinated object access
- product_with_stock and two_branches_with_stock composite fixtures
```

```
feat(core): add BranchScopeQuerysetMixin for branch-scoped data access

- Mixin centralizes branch-filtering policy in one place
- Default get_branch_q filters by single branch_field FK
- Subclasses override get_branch_q for OR conditions (movement history)
- Sellers see outgoing and incoming movements for their branch
- StockListView intentionally bypasses mixin: sellers have global read
  visibility on stock per BUSINESS_RULES §1.2
```

```
feat(core): update MovementCursorPagination to compound ordering (-created_at, id)

- Single created_at ordering is unstable under concurrent inserts:
  two records with same timestamp produce non-unique cursor position
- id is strictly monotonic in PostgreSQL (sequence never repeats)
- Compound (created_at DESC, id ASC) is always unique and stable
- CursorPagination avoids COUNT(*) query; uses indexed WHERE clause
  for O(log N) pagination regardless of table size
```

```
feat(movements): add extend_schema OpenAPI annotations to all APIView endpoints

- drf-spectacular cannot auto-document APIView (no declared serializer)
- Add @extend_schema with request, responses, summary, and tags
- Define shared OpenApiResponse objects for reused error descriptions
- Tags: Movements, Movements - Transfers, Stock
- GenericAPIView endpoints left unannotated (auto-generation is correct)
```

```
test(permissions): add permission test suite mapped to BUSINESS_RULES.md

- TestUnauthenticated: parametrize 9 critical endpoints, all must return 401
- TestSellerPermissions: 9 tests covering all seller restrictions
- TestMovementHistoryScoping: 4 tests verifying queryset isolation per role
- TestAdminPermissions: 5 tests verifying admin can perform all operations
- TestTransferFlowPermissions: 3 tests for two-step flow edge cases
- TestUserRoleIntegrity: 2 tests for role-branch constraint enforcement
```

---

## Phase 4 — Reversal System, N+1 Audit, and Test Consistency

```
feat(movements): add REVERSAL movement type to MovementType choices

- New REVERSAL value created exclusively by the reversal service
- Clients cannot post movement_type=reversal directly (no serializer exposes it)
- DB constraints remain valid: reversals are always status=confirmed
```

```
feat(movements): implement reversal system with strategy pattern

- StockMovementService.revertir() dispatches to type-specific strategy functions
- _REVERSAL_STRATEGIES dict maps each MovementType to a handler function
- Four ordered guards before strategy dispatch (cheapest check first):
  pending transfer, non-confirmed, reversal-of-reversal, already reversed
- _reverse_ingreso, _reverse_venta, _reverse_transferencia, _reverse_ajuste,
  _reverse_devolucion, _reverse_donacion private strategy functions
- Transfer reversal acquires locks in same ascending branch_id order
  as original transfer to prevent deadlocks
- Ajuste reversal handles zero-quantity edge case with Decimal("0.001")
  in quantity field; real value preserved in adjustment_previous_quantity
- _create_reversal_record centralises reversal movement creation
- OneToOneField on reverses_movement enforces at-most-one reversal per movement
```

```
feat(movements): add POST /movements/{id}/reverse/ endpoint

- Admin-only; seller access returns 403
- Returns created reversal movement with HTTP 201
- Add @extend_schema annotation with all error response codes
- Add URL to movements/urls.py
```

```
test(movements): add reversal tests for all movement types and edge cases

- Happy path test for each of the 6 reversible movement types
- Insufficient stock tests for ingreso, transferencia, devolucion reversals
- TestReversalEdgeCases: cannot reverse twice, cannot reverse a reversal,
  original movement is immutable after reversal, endpoint returns 201,
  seller cannot call reversal endpoint
```

```
test: add N+1 query count audit using django_assert_num_queries

- test_movement_list_no_n_plus_one: expects 1 query for admin (CursorPagination
  has no COUNT query; select_related fetches all relations in one JOIN)
- test_movement_list_seller_scope_no_n_plus_one: expects 1 query for seller
  (branch scope filter applied in same query)
- test_stock_list_no_n_plus_one: expects 2 queries (data + COUNT for
  StandardPagination)
- test_venta_query_count: expects 3 queries (lock + update + insert)
- test_transferencia_create_query_count: expects 3 queries
- test_transferencia_confirm_query_count: expects 4 queries (includes
  select_for_update on movement to prevent concurrent double-confirmation)
- test_product_list_no_n_plus_one: expects 2 queries
```

```
refactor(test): migrate test_services setUp methods to factory_boy

- Replace make_admin/make_branch/make_product/make_stock helpers with
  AdminFactory/BranchFactory/ProductFactory/StockFactory
- Remove all manual helper functions from test_services.py
- Assertions untouched; only setUp changed
- Project now uses factory_boy consistently across all test modules
```

---

## Security

```
security: upgrade password hashing to Argon2id with explicit parameters

- Add argon2-cffi==23.1.0 to requirements/base.txt
- Add core/hashers.py with StockArgon2PasswordHasher subclassing
  Argon2PasswordHasher with explicit, documented parameters:
  time_cost=2, memory_cost=65536 (64 MiB), parallelism=1,
  salt_len=16 (128-bit random salt via os.urandom), hash_len=32
- Configure PASSWORD_HASHERS in settings with Argon2 as primary and
  PBKDF2 as fallback for transparent rehashing of existing passwords
- 64 MiB memory_cost exceeds OWASP minimum (19 MiB); primary defence
  against GPU brute-force attacks on exposed internet-facing system
- Django rehashes existing PBKDF2 passwords to Argon2 automatically
  on each user's next successful login; no manual migration required
```
