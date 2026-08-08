"""
tests/test_query_count.py

Performance contract tests — verify that list endpoints do not produce
N+1 queries regardless of how many rows are returned.

These tests use `django_assert_num_queries` (provided by pytest-django)
to make the query count an explicit, version-controlled assertion.
If a refactor accidentally removes a select_related or prefetch_related,
these tests fail before the code reaches production.

Convention:
  - Each test creates a realistic number of rows (10-20) with different
    related objects so that an N+1 bug is always detectable.
  - Allowed query counts are documented inline with the reason each
    query is expected.
  - `force_authenticate` is used so JWT middleware does not add extra queries.

Run: pytest apps/movements/tests/test_query_count.py -v
"""
import pytest
from decimal import Decimal

from tests.factories import (
    AdminFactory,
    SellerFactory,
    BranchFactory,
    ProductFactory,
    StockFactory,
    StockMovementFactory,
    CategoryFactory,
)
from tests.helpers import idempotent_post


# ---------------------------------------------------------------------------
# Movement history
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_movement_list_no_n_plus_one(admin_client, django_assert_num_queries):
    """
    GET /api/v1/movements/ must execute exactly 1 query regardless of result size.

    Expected queries:
      1. SELECT movements with select_related(product, source_branch,
         destination_branch, created_by) — fetches everything in one JOIN.

    CursorPagination does NOT issue a COUNT query (unlike PageNumberPagination),
    which is one of the reasons it was chosen for the history endpoint.
    """
    client, admin = admin_client

    # Create 15 movements with different products, branches, and users
    # so that an N+1 bug on any related field is detectable.
    branches  = [BranchFactory() for _ in range(3)]
    products  = [ProductFactory() for _ in range(3)]
    for i in range(15):
        StockMovementFactory(
            product=products[i % 3],
            source_branch=branches[i % 3],
            created_by=admin,
        )

    with django_assert_num_queries(1):
        response = client.get("/api/v1/movements/")

    assert response.status_code == 200
    assert len(response.data["results"]) == 15


@pytest.mark.django_db
def test_movement_list_seller_scope_no_n_plus_one(seller_client, django_assert_num_queries):
    """
    GET /api/v1/movements/ for a seller must still execute exactly 1 query.
    The branch scope filter (WHERE source_branch=X OR destination_branch=X)
    is applied in the same query — it must not trigger extra lookups.
    """
    client, user, branch = seller_client
    product = ProductFactory()

    for _ in range(10):
        StockMovementFactory(
            product=product,
            source_branch=branch,
            created_by=AdminFactory(),
        )

    with django_assert_num_queries(1):
        response = client.get("/api/v1/movements/")

    assert response.status_code == 200
    assert len(response.data["results"]) == 10


# ---------------------------------------------------------------------------
# Stock list
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_stock_list_no_n_plus_one(admin_client, django_assert_num_queries):
    """
    GET /api/v1/stock/ must execute exactly 2 queries:
      1. SELECT stock with select_related(product, product__category, branch)
      2. COUNT for PageNumberPagination (StockListView uses StandardPagination)
    """
    client, admin = admin_client

    branches  = [BranchFactory()  for _ in range(4)]
    products  = [ProductFactory(category=CategoryFactory()) for _ in range(4)]
    for b in branches:
        for p in products:
            StockFactory(product=p, branch=b, quantity=Decimal("10"))

    with django_assert_num_queries(2):
        response = client.get("/api/v1/stock/")

    assert response.status_code == 200
    assert response.data["count"] == 16  # 4 branches × 4 products


# ---------------------------------------------------------------------------
# Write operations — verify atomic transactions don't produce extra reads
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_venta_query_count(admin_client, django_assert_num_queries):
    """
    POST /api/v1/movements/venta/ must execute exactly 6 queries as of
    Phase 8 (was 3 before idempotency enforcement — see docs/phase8_prompt.md
    Part 3):

      Idempotency layer (apps/idempotency/mixins.py, first-time key):
      1. SELECT idempotency_key WITH select_for_update() — miss
      2. INSERT idempotency_key placeholder row (get_or_create's create())

      Original business operation (unchanged):
      3. SELECT stock row WITH select_for_update() lock
      4. UPDATE stock row
      5. INSERT StockMovement record

      Idempotency layer (after success):
      6. UPDATE idempotency_key row with the final response

    ⚠️ ESTIMATED COUNT — not verified against a real Postgres run in the
    environment this was written in (no DB access available there). This
    reasoning does NOT account for possible extra SAVEPOINT/RELEASE
    SAVEPOINT statements from nesting transaction.atomic() (mixin) inside
    django_assert_num_queries' own transaction wrapping, which may or may
    not be counted depending on the Django/pytest-django version — the
    existing pre-Phase-8 baseline of 3 (not 5, if savepoints were counted)
    suggests they aren't counted in this setup, so this estimate assumes
    the same. Run this test; if it fails, the actual number
    django_assert_num_queries reports is correct — replace the 6 below
    and update this docstring to match, do not adjust to make it pass
    without understanding why the real count differs.
    """
    client, admin = admin_client
    branch  = BranchFactory()
    product = ProductFactory()
    StockFactory(product=product, branch=branch, quantity=Decimal("50"))

    with django_assert_num_queries(6):
        response = idempotent_post(client, "/api/v1/movements/venta/", {
            "product":  product.id,
            "branch":   branch.id,
            "quantity": "5.000",
        }, format="json")

    assert response.status_code == 201


@pytest.mark.django_db
def test_transferencia_create_query_count(admin_client, django_assert_num_queries):
    """
    POST /api/v1/movements/transferencia/ (step 1, creates PENDING) must
    execute exactly 6 queries as of Phase 8 (was 3 — see the detailed
    breakdown and the ⚠️ ESTIMATED COUNT caveat on test_venta_query_count
    above, which applies identically here):

      1. SELECT idempotency_key WITH select_for_update() — miss
      2. INSERT idempotency_key placeholder row
      3. SELECT source stock WITH select_for_update()
      4. UPDATE source stock (decrement reservation)
      5. INSERT StockMovement record (PENDING)
      6. UPDATE idempotency_key row with the final response
    """
    client, admin = admin_client
    branch_a = BranchFactory()
    branch_b = BranchFactory()
    product  = ProductFactory()
    StockFactory(product=product, branch=branch_a, quantity=Decimal("30"))

    with django_assert_num_queries(6):
        response = idempotent_post(client, "/api/v1/movements/transferencia/", {
            "product":            product.id,
            "source_branch":      branch_a.id,
            "destination_branch": branch_b.id,
            "quantity":           "10.000",
        }, format="json")

    assert response.status_code == 201


@pytest.mark.django_db
def test_transferencia_confirm_query_count(admin_client, django_assert_num_queries):
    """
    POST /api/v1/movements/transferencia/{id}/confirm/ (step 2) must
    execute exactly 7 queries as of Phase 8 (was 4 — see the ⚠️ ESTIMATED
    COUNT caveat on test_venta_query_count above, which applies
    identically here):

      1. SELECT idempotency_key WITH select_for_update() — miss
      2. INSERT idempotency_key placeholder row
      3. SELECT + lock the movement row (select_for_update on StockMovement)
      4. SELECT (get_or_create) + lock destination stock row
      5. UPDATE destination stock (increment)
      6. UPDATE movement status to CONFIRMED
      7. UPDATE idempotency_key row with the final response
    """
    client, admin = admin_client
    branch_a = BranchFactory()
    branch_b = BranchFactory()
    product  = ProductFactory()
    StockFactory(product=product, branch=branch_a, quantity=Decimal("30"))

    create_resp = idempotent_post(client, "/api/v1/movements/transferencia/", {
        "product":            product.id,
        "source_branch":      branch_a.id,
        "destination_branch": branch_b.id,
        "quantity":           "10.000",
    }, format="json")
    movement_id = create_resp.data["id"]

    with django_assert_num_queries(7):
        response = idempotent_post(
            client, f"/api/v1/movements/transferencia/{movement_id}/confirm/",
            format="json",
        )

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Product and branch lists (simpler but also worth auditing)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_product_list_no_n_plus_one(admin_client, django_assert_num_queries):
    """
    GET /api/v1/products/ must execute exactly 2 queries:
      1. SELECT products with select_related(category)
      2. COUNT for pagination
    """
    client, admin = admin_client
    category = CategoryFactory()
    for _ in range(12):
        ProductFactory(category=category)

    with django_assert_num_queries(2):
        response = client.get("/api/v1/products/")

    assert response.status_code == 200
    assert response.data["count"] == 12
