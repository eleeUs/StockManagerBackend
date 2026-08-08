"""
apps/movements/tests/test_idempotency_wiring.py

Part 2 scope: proves IdempotentMutationMixin is correctly wired into the
real endpoints, end-to-end over HTTP. Tests against VentaView as the
representative endpoint — the mixin itself is already fully tested in
isolation in apps/idempotency/tests/test_services.py (Part 1); this file
is not re-testing that logic, only that it's actually attached and that
DRF's request lifecycle (permissions vs. idempotency ordering) behaves
as designed.

Per docs/phase8_prompt.md, the ~40 pre-existing call sites elsewhere in
this test suite are EXPECTED to fail with 400 idempotency_key_required
at the end of Part 2 — that's fixed in Part 3, not here.
"""
import uuid

import pytest
from decimal import Decimal

from tests.factories import ProductFactory, StockFactory


def _venta_payload(product, branch, quantity="1"):
    return {"product": product.id, "branch": branch.id, "quantity": quantity}


@pytest.mark.django_db
class TestIdempotencyEnforcement:

    def test_missing_header_returns_400(self, admin_client, product_with_stock):
        client, _ = admin_client
        product, branch, stock = product_with_stock

        response = client.post("/api/v1/movements/venta/", _venta_payload(product, branch))

        assert response.status_code == 400
        assert response.data["error"] == "idempotency_key_required"

    def test_present_header_succeeds(self, admin_client, product_with_stock):
        client, _ = admin_client
        product, branch, stock = product_with_stock
        key = str(uuid.uuid4())

        response = client.post(
            "/api/v1/movements/venta/", _venta_payload(product, branch),
            HTTP_IDEMPOTENCY_KEY=key,
        )

        assert response.status_code == 201

    def test_replay_same_key_same_body_returns_cached_response_without_re_executing(
        self, admin_client, product_with_stock,
    ):
        client, _ = admin_client
        product, branch, stock = product_with_stock
        starting_quantity = stock.quantity
        key = str(uuid.uuid4())
        payload = _venta_payload(product, branch, quantity="3")

        first = client.post("/api/v1/movements/venta/", payload, HTTP_IDEMPOTENCY_KEY=key)
        second = client.post("/api/v1/movements/venta/", payload, HTTP_IDEMPOTENCY_KEY=key)

        assert first.status_code == 201
        assert second.status_code == 201
        assert second.data == first.data  # byte-identical replay, not a new movement

        stock.refresh_from_db()
        # Only debited once — this is the actual point of the whole feature.
        assert stock.quantity == starting_quantity - Decimal("3")

    def test_replay_same_key_different_body_returns_409(self, admin_client, product_with_stock):
        client, _ = admin_client
        product, branch, stock = product_with_stock
        key = str(uuid.uuid4())

        first = client.post(
            "/api/v1/movements/venta/", _venta_payload(product, branch, "1"),
            HTTP_IDEMPOTENCY_KEY=key,
        )
        second = client.post(
            "/api/v1/movements/venta/", _venta_payload(product, branch, "2"),
            HTTP_IDEMPOTENCY_KEY=key,
        )

        assert first.status_code == 201
        assert second.status_code == 409
        assert second.data["error"] == "idempotency_key_conflict"

    def test_failed_attempt_is_not_cached_and_retry_is_a_fresh_attempt(
        self, admin_client, product_with_stock,
    ):
        client, _ = admin_client
        product, branch, stock = product_with_stock
        key = str(uuid.uuid4())
        # More than available — guaranteed to fail.
        too_much = str(stock.quantity + Decimal("1000"))

        failed = client.post(
            "/api/v1/movements/venta/", _venta_payload(product, branch, too_much),
            HTTP_IDEMPOTENCY_KEY=key,
        )
        assert failed.status_code == 400
        assert failed.data["error"] == "insufficient_stock"

        # Same key, now a request that should actually succeed. Must NOT
        # be treated as a replay of the failed attempt, and must not 409
        # either — the failed attempt was never cached.
        retry = client.post(
            "/api/v1/movements/venta/", _venta_payload(product, branch, "1"),
            HTTP_IDEMPOTENCY_KEY=key,
        )
        assert retry.status_code == 201

    def test_seller_wrong_branch_403_is_not_cached_either(self, seller_client, product_with_stock):
        """
        VentaView's own explicit 403 (seller/wrong-branch) is returned
        as a Response, not raised — confirms the mixin's manual
        transaction.set_rollback() path (needed because
        transaction.atomic() only auto-rolls-back on a propagated
        exception) covers this case too, not just raised exceptions.
        """
        client, user, own_branch = seller_client
        product, other_branch, stock = product_with_stock  # different branch than the seller's
        key = str(uuid.uuid4())

        response = client.post(
            "/api/v1/movements/venta/", _venta_payload(product, other_branch),
            HTTP_IDEMPOTENCY_KEY=key,
        )
        assert response.status_code == 403

        # Retry with the same key against the seller's OWN branch — must
        # not 409, proving the 403 attempt was rolled back, not cached.
        StockFactory(product=product, branch=own_branch, quantity=Decimal("10"))
        retry = client.post(
            "/api/v1/movements/venta/", _venta_payload(product, own_branch),
            HTTP_IDEMPOTENCY_KEY=key,
        )
        assert retry.status_code == 201


@pytest.mark.django_db
class TestIdempotencyPermissionOrdering:
    """
    Permission failures must win over idempotency failures — an
    unauthorized caller should never learn anything about this endpoint's
    idempotency requirements. See IdempotentMutationMixin's module
    docstring for why hooking post() (not dispatch()/initial()) guarantees
    this ordering.
    """

    def test_unauthenticated_gets_401_not_400_even_without_header(self, api_client):
        product = ProductFactory()
        branch_payload = {"product": product.id, "branch": 1, "quantity": "1"}

        response = api_client.post("/api/v1/movements/ingreso/", branch_payload)

        assert response.status_code == 401

    def test_seller_hitting_admin_only_endpoint_gets_403_not_400(self, seller_client):
        """IngresoView is admin-only; a seller calling it without the
        header must get 403 (unauthorized), never 400 (missing header)."""
        client, user, branch = seller_client
        product = ProductFactory()

        response = client.post(
            "/api/v1/movements/ingreso/",
            {"product": product.id, "branch": branch.id, "quantity": "1", "entry_date": "2026-01-01"},
        )

        assert response.status_code == 403


@pytest.mark.django_db
class TestIdempotencyRequiredSettingOverride:

    def test_missing_header_allowed_when_setting_disabled(
        self, admin_client, product_with_stock, settings,
    ):
        settings.IDEMPOTENCY_KEY_REQUIRED = False
        client, _ = admin_client
        product, branch, stock = product_with_stock

        response = client.post("/api/v1/movements/venta/", _venta_payload(product, branch))

        assert response.status_code == 201
