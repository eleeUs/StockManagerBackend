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


---

## Phase 5 — Migrations, Throttling, Password Change, Production Readiness

```
feat(migrations): add initial migrations for all apps in dependency order

- apps/branches/migrations/0001_initial.py: Branch model
- apps/products/migrations/0001_initial.py: Category and Product models
- apps/users/migrations/0001_initial.py: custom User model with CheckConstraint
  and M2M to auth.Group and auth.Permission; depends on branches
- apps/stock/migrations/0001_initial.py: Stock model with unique_together,
  two compound indexes, and non-negativity CheckConstraint
- apps/movements/migrations/0001_initial.py: StockMovement with self-referential
  OneToOneField (reverses_movement), five indexes, three CheckConstraints;
  uses swappable_dependency(AUTH_USER_MODEL)
```

```
feat(users): add seed_dev_data management command

- Creates 3 branches, 3 categories, 8 products, 4 users, and initial stock
- Fully idempotent via get_or_create — safe to run multiple times
- --flush flag drops all data before seeding with interactive confirmation
- Prints summary with created/skipped status per record
- Admin credentials: admin@stockapp.dev / admin1234!
```

```
feat(core): add LoginRateThrottle and global API throttle rates

- Add LoginRateThrottle(AnonRateThrottle) with scope='login' in core/views.py
- Apply throttle_classes=[LoginRateThrottle] on LoginView only
- Add DEFAULT_THROTTLE_CLASSES and DEFAULT_THROTTLE_RATES to settings:
  login=5/minute (per IP), user=200/minute, anon=20/minute
- 5/min × Argon2 (~100ms/attempt) makes brute-force computationally infeasible
- Document rate rationale in LoginRateThrottle docstring
```

```
feat(users): add POST /auth/change-password/ endpoint

- Add ChangePasswordSerializer with four validation rules:
  current_password must match stored hash, new_password >= 8 chars,
  confirm_password must equal new_password, new != current
- Add ChangePasswordView returning 204 No Content on success
- set_password() applies Argon2id hasher automatically
- Only password and updated_at written to DB (update_fields)
- Add URL at /api/v1/auth/change-password/
```

```
feat(core): add HealthCheckView at GET /health/

- No authentication or throttling — accessible by monitoring tools
- Executes SELECT 1 to verify DB connection is alive
- Returns {"status": "ok", "database": "ok"} with HTTP 200
- Returns {"status": "error", "database": "unavailable"} with HTTP 503
- Register in config/urls.py outside the api/v1/ prefix
```

```
feat(core): add RequestIDMiddleware and RequestIDFilter for request tracing

- RequestIDMiddleware reads X-Request-ID from incoming headers or generates uuid4
- Attaches ID to request.request_id and thread-local storage
- Writes X-Request-ID to every response header
- Clears thread-local on response to prevent leakage between requests
  in gunicorn sync workers that reuse OS threads
- RequestIDFilter(logging.Filter) injects request_id into every log record
- Update LOGGING config to use RequestIDFilter and include %(request_id)s
  in the verbose formatter
- Position middleware second in MIDDLEWARE stack (after SecurityMiddleware)
```

```
feat(ops): add gunicorn config and production docker-compose override

- Add gunicorn.conf.py with sync workers (CPU*2+1), timeout=30,
  max_requests=1000 with jitter, accesslog/errorlog to stdout
- Worker model rationale: select_for_update() is incompatible with
  greenlet-based async workers; sync workers block correctly on DB locks
- Add docker-compose.prod.yml as override file with gunicorn CMD
  and REQUIREMENTS=production build arg
- Update Dockerfile with ARG REQUIREMENTS for dev/prod requirement split
```

```
test(phase5): add tests for health check, rate limiting, password change,
and request ID propagation

- TestHealthCheck: 200 when DB ok, no auth required, 503 when DB down,
  response shape always includes both fields
- TestLoginRateLimit: success within limit, 429 when throttled (mock),
  throttle not applied to other endpoints
- TestChangePassword: success 204, password actually changed in DB,
  wrong current password, mismatched passwords, same password, too short,
  unauthenticated returns 401
- TestRequestID: response includes header, custom ID propagated,
  server generates valid UUID when none provided
```

---

## Phase 6 — Reporting, Security Hardening, and CI/CD

```
feat(reports): add apps/reports with low stock, movement summary, and
branch activity endpoints

- Models-less app, intentionally not registered in INSTALLED_APPS
- LowStockReportView: reuses StockSerializer + StandardPagination;
  sellers scoped to their own branch via BranchScopeQuerysetMixin.get_branch_q()
- MovementSummaryReportView: annotate(count, total_quantity) grouped by
  movement_type over a required date_from/date_to window; admin only
- BranchActivityReportView: summary_by_type + daily_breakdown via
  TruncDate; admin only; 404 on unknown branch id
- All three views annotated with @extend_schema, tagged "Reports"
- Registered at /api/v1/reports/ in config/urls.py
```

```
test(reports): add test_reports.py covering all three report endpoints

- Happy path, threshold filtering, and seller branch scoping for A1
- Date-range filtering and aggregation correctness for A2
- Daily breakdown correctness, unknown-branch 404, and cross-branch
  exclusion for A3
- Admin-only access verified (403) for A2 and A3
- Test data exclusively from tests/factories.py; StockMovementFactory
  used directly since these are read-only tests
```

```
feat(security): add django-cors-headers with environment-scoped origins

- CORS_ALLOW_ALL_ORIGINS=False and empty CORS_ALLOWED_ORIGINS in base.py
  as a fail-safe default
- development.py: CORS_ALLOW_ALL_ORIGINS=True for local frontend work
- production.py: CORS_ALLOWED_ORIGINS read from env as an explicit list
- CorsMiddleware placed immediately before CommonMiddleware per
  django-cors-headers positioning requirement
```

```
security: add SECURE_PROXY_SSL_HEADER and SECURE_HSTS_PRELOAD to production

- SECURE_PROXY_SSL_HEADER required behind a TLS-terminating reverse proxy;
  without it SECURE_SSL_REDIRECT causes a redirect loop
- SECURE_HSTS_PRELOAD enables browser HSTS preload list submission
```

```
chore: add .dockerignore

- Excludes .env, .git, __pycache__, .pytest_cache, coverage artefacts,
  docs/, and editor directories from the build context
- requirements/ intentionally not excluded — needed at build time
```

```
ci: add GitHub Actions workflow with parallel lint and test jobs

- lint job: ruff check + ruff format --check, no database needed
- test job: postgres:16-alpine service container with pg_isready
  healthcheck, migrate, then pytest --tb=short -q
- Triggers on push and pull_request to main and develop
- Add pyproject.toml with ruff config (line-length=100, py312 target,
  E/F/I/W rule sets)
- Add ruff==0.4.4 to requirements/development.txt
```

```
chore: add Makefile with docker-compose command shortcuts

- Targets: help, build, up, down, migrate, seed, test, test-v, lint,
  shell, logs, prod-up
- All targets marked .PHONY
```

```
build: convert Dockerfile to a multi-stage build

- builder stage (python:3.12-slim): installs gcc/libffi-dev/libpq-dev,
  pip installs into --prefix=/install
- runtime stage (python:3.12-slim): copies only /install from builder;
  no compiler toolchain in the final image
- psycopg2-binary bundles libpq and argon2-cffi ships binary wheels,
  so no apt packages are needed at runtime
- ARG REQUIREMENTS=development redeclared in both stages (Docker scopes
  build args per stage)
```

---

## Phase 7 — Valorización, Proveedores y Alertas de Stock

```
feat(products): add cost_price and sale_price to Product

- Both nullable DecimalField(max_digits=12, decimal_places=2),
  MinValueValidator(0) — not every product has pricing loaded on day one
- cost_price stripped from ProductSerializer.to_representation() for
  sellers (margin-sensitive data); sale_price stays visible to both roles
- Restriction applies automatically to every call site (list, detail),
  not only a single endpoint
```

```
feat(suppliers): add apps/suppliers with Supplier CRUD

- Model: name (unique), contact_name, contact_email, contact_phone,
  is_active, timestamps
- List/detail views mirror apps/branches: both roles can list (sellers
  see active only), admin-only create/update
- Never hard-deleted — deactivate via is_active=False, PROTECT on FK
  from StockMovement.supplier enforces this at the DB level
- Registered in INSTALLED_APPS (has real state/migrations, unlike the
  models-less apps/reports from Phase 6)
- Registered at /api/v1/suppliers/ in config/urls.py
```

```
feat(movements): add optional supplier FK to StockMovement, ingreso only

- supplier FK nullable, PROTECT on_delete
- movement_supplier_only_for_ingreso CheckConstraint: any movement type
  other than ingreso storing a supplier is invalid at the DB level
- IngresoSerializer accepts optional supplier; StockMovementService.ingreso
  accepts supplier_id; IngresoView passes it through
- StockMovementSerializer (read) exposes supplier + supplier_name
```

```
feat(stock): add reorder_point to Stock, per (product, branch) row

- Nullable DecimalField — null means no alert configured for this row,
  not "use a global default"
- Deliberately per-row, not a system-wide setting: demand for the same
  product legitimately differs by branch
- PATCH /api/v1/stock/{id}/reorder-point/ (admin only) touches only this
  field via a narrow serializer — quantity remains reachable exclusively
  through StockMovementService, this endpoint doesn't widen that boundary
```

```
feat(stock): add check_low_stock management command

- Scans Stock rows with reorder_point set where quantity <= reorder_point
- Logs each match and prints a summary; --webhook-url POSTs a JSON
  payload via urllib.request (stdlib) — no new dependency added
- Designed for external scheduling (cron, k8s CronJob); project has no
  task queue by design (phase6_prompt.md constraint)
```

```
feat(reports): add GET /reports/stock/valuation/

- Admin only, same rationale as cost_price itself being admin-only
- quantity * cost_price aggregated by branch and by product via
  ExpressionWrapper + Sum at the DB level
- Rows with no cost_price are excluded from the total, never treated as
  worth zero — products_missing_cost_price reports how many are missing
  so the total's completeness is never ambiguous
```

```
test: add Phase 7 coverage across suppliers, stock, products, movements, reports

- apps/suppliers/tests/test_suppliers.py: CRUD + permission tests
- apps/stock/tests/test_reorder_point.py: admin-only, never touches
  quantity, null clears the alert, negative value rejected
- apps/stock/tests/test_check_low_stock.py: command output, rows without
  reorder_point skipped, webhook payload shape (mocked urlopen)
- apps/products/tests/test_pricing.py: cost_price hidden from sellers in
  both list and detail, sale_price always visible, negative price rejected
- apps/movements/tests/test_supplier_ingreso.py: service accepts
  supplier_id, DB constraint rejects supplier on non-ingreso movements,
  endpoint round-trip with and without supplier
- apps/reports/tests/test_reports.py: TestStockValuationReport — total
  valuation, missing-cost-price exclusion and count, branch filter,
  by_branch/by_product breakdown shape
- tests/factories.py: add SupplierFactory, ProductFactory now sets
  cost_price/sale_price defaults
```

```
chore(seed): add suppliers and per-product pricing to seed_dev_data

- New SUPPLIERS list seeded via get_or_create, same idempotent pattern
  as the rest of the command
- PRODUCTS entries now include cost_price/sale_price so the valuation
  report has real data to show against a fresh seed
```

```
fix(test): replace undefined make_stock() call with StockFactory

- test_ingreso_adds_to_existing_stock referenced make_stock(...), a
  helper removed in the Phase 4 factory_boy refactor that missed this
  call site — StockFactory was already imported in the same file
- Pre-existing bug, unrelated to Phase 7 scope; fixed in passing since
  it broke test collection for this file
```

---

## Phase 8, Part 1 — Idempotency Foundations

```
feat(idempotency): add apps/idempotency with IdempotencyKey model

- (user, key, endpoint) unique constraint; no status/state-machine field
  by design — a row only ever exists in a fully-committed success state,
  see the model's docstring for the rollback-semantics rationale
- response_body uses DjangoJSONEncoder so Decimal/date/datetime values
  from a DRF serializer's .data never fail JSON storage
- expires_at + index, for cleanup_idempotency_keys (Part 3)
- Registered in LOCAL_APPS (has real state, unlike the models-less
  apps/reports from Phase 6)
```

```
feat(idempotency): add IdempotencyService with get_or_create_and_lock

- hash_body(): deterministic, order-independent sha256 of the request body
- get_or_create_and_lock(): mirrors the get_or_create + select_for_update
  pattern already used in apps/movements/services.py; MUST be called
  inside a transaction.atomic() block the caller controls
- Raises IdempotencyKeyConflictError on hash mismatch for a reused key —
  never silently replay a response for a different logical request
```

```
feat(core): add IdempotencyError hierarchy, separate from StockDomainError

- IdempotencyKeyRequiredError → 400 idempotency_key_required
- IdempotencyKeyConflictError → 409 idempotency_key_conflict
- Kept as its own base, not under StockDomainError — a cross-cutting
  HTTP concern, not a stock business rule
```

```
feat(idempotency): add IdempotentMutationMixin, not wired to any view yet

- Hooks post(), not dispatch()/initial() — permission_classes checks run
  in DRF's initial(), always before a handler; hooking post() gets
  permission-before-idempotency ordering for free without reimplementing
  DRF internals
- IDEMPOTENCY_KEY_REQUIRED setting added (default True everywhere,
  including its own default value) as an operational escape hatch
```

```
test(idempotency): add service + rollback + concurrency tests

- Hash determinism, first-call/replay/conflict behavior for
  get_or_create_and_lock
- Rollback test: proves a row does NOT persist if the wrapped operation
  raises inside the same transaction.atomic() block the mixin will use —
  the test that validates the whole "no status field" design before
  Part 2 depends on it
- Concurrency test with real threads (TransactionTestCase, same pattern
  as TestConcurrentVenta): exactly one of two simultaneous callers with
  the same key gets created=True
- Verified zero behavioral change to any Phase 1-7 endpoint: the mixin
  is built but referenced nowhere outside apps/idempotency/
```

```
chore: add VS Code testing configuration

- .vscode/settings.json + launch.json for the pytest Test Explorer
- .env.test.local.example: separate env file for running tests directly
  from VS Code (host "localhost") vs. docker-compose (host "db")
- docs/vscode-testing.md with full setup + troubleshooting
```

---

## Phase 8, Part 2 — Enforcement

```
feat(movements): wire IdempotentMutationMixin into all nine write views

- Ingreso, Venta, Transferencia, ConfirmTransfer, CancelTransfer,
  Ajuste, Devolucion, Donacion, ReverseMovement: post() renamed to
  perform_mutation(), IdempotentMutationMixin added to bases
- Confirmed by design (and by locating VentaView's own explicit 403
  seller/wrong-branch Response, which doesn't raise) that the mixin's
  manual transaction.set_rollback() path is necessary, not redundant
  with automatic rollback-on-exception
```

```
feat(movements): move OpenAPI schema for the 9 write views to extend_schema_view

- @extend_schema on perform_mutation() would be invisible to
  drf-spectacular, which resolves schema from a method literally named
  after the HTTP verb (post) — extend_schema_view maps schema to an
  operation by name regardless of where in the MRO it's implemented
- Added the Idempotency-Key header parameter + 409 conflict response to
  all nine; merged the 409 description on ConfirmTransferView,
  CancelTransferView, and ReverseMovementView (which already used 409
  for their own business case) rather than silently overwriting it
```

```
docs: add BUSINESS_RULES.md §12 — idempotency

- Which endpoints require the header, replay/conflict/failed-attempt
  behavior, (user, key, endpoint) scoping, and the
  IDEMPOTENCY_KEY_REQUIRED escape hatch framed explicitly as an
  emergency lever, not a supported steady state
```

```
test(movements): add end-to-end idempotency wiring tests

- Against VentaView as the representative endpoint (the mixin itself is
  already fully unit-tested in Part 1)
- Missing header → 400; replay → cached response, stock debited once;
  conflicting body → 409; failed attempt (insufficient stock) is not
  cached and a retry is a fresh attempt; VentaView's explicit 403 is
  not cached either
- Permission-ordering tests: unauthenticated → 401 not 400; seller on
  an admin-only endpoint → 403 not 400, even with no header sent
- Expected and confirmed: ~40 pre-existing call sites elsewhere in the
  suite now fail with 400 idempotency_key_required — scoped fallout,
  fixed in Part 3
```

---

## Phase 8, Part 3 — Fallout Cleanup and Audit Trail

```
test: add tests/helpers.py::idempotent_post and fix ~40 call sites

- Auto-generates a fresh UUID key per call by default
- Did NOT default the header via client.credentials() on the shared
  admin_client/seller_client fixtures — several tests reuse one client
  for two distinct write calls (create-then-confirm a transfer); a
  static default key would make them collide into a false 409
- Two call sites needed distinct keys specifically verified by hand:
  test_cannot_confirm_already_confirmed_transfer and
  test_cannot_cancel_confirmed_transfer both call confirm/cancel twice
  expecting the second call's 409 to be the real business error, not an
  idempotency conflict with the same status code but the wrong reason
- Updated: test_permissions.py, test_query_count.py,
  test_supplier_ingreso.py, test_reversals.py
```

```
test(movements): update query-count contracts for idempotency overhead

- test_venta_query_count, test_transferencia_create_query_count,
  test_transferencia_confirm_query_count: 3/3/4 → 6/6/7
- +3 queries per write endpoint: SELECT-for-update miss, INSERT
  placeholder row, UPDATE with final response
- Numbers are a reasoned estimate, explicitly flagged in each docstring
  as unverified against a real Postgres run — no DB access in the
  environment this was written in
- docs/phase-4.md's query-count table updated to match, cross-referenced
  to docs/phase-8.md
```

```
feat(idempotency): add cleanup_idempotency_keys management command

- Same cron-facing shape as check_low_stock (Phase 7): no task queue
- Deletes IdempotencyKey rows past expires_at; --dry-run supported
```

```
feat(audit): add apps/audit with AuditLog for Product, Branch, User

- (model_name, object_id) pair, not GenericForeignKey — three known
  models, not an open-ended set; avoids a django_content_type join
- Not django-simple-history — its default user-capture assumes
  session-based auth populates request.user before its middleware runs;
  this project's JWT-inside-DRF auth only resolves request.user inside
  a view, same reason IdempotentMutationMixin is a DRF mixin and not
  Django middleware (Part 1)
- AuditedUpdateMixin.perform_update(): diffs only the fields the request
  actually touched, captured explicitly at the point request.user is
  known — not via pre_save/post_save signals, which have no reliable
  access to the current user without thread-locals (and wouldn't work
  during seed_dev_data, which has no request)
- is_active=False specifically recorded as action=deactivate
- Wired into ProductDetailView, BranchDetailView, UserDetailView
- GET /api/v1/audit-log/ read endpoint, admin only, filterable by
  model + object_id
```

```
docs: add BUSINESS_RULES.md §13 — audit trail

- What's recorded, explicit scope exclusions (admin/shell changes,
  StockMovement's own existing audit trail, password changes), and who
  can read it
```

```
docs: add docs/phase-8.md covering all three parts

- Includes the two technical findings made while implementing, not
  anticipated in docs/phase8_prompt.md's original plan: the
  extend_schema_view requirement (Part 2) and VentaView's explicit
  non-raising 403 confirming the mixin's manual rollback path is
  necessary (Part 1/2)
```
