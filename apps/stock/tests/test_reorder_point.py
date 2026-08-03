"""
apps/stock/tests/test_reorder_point.py

Covers PATCH /api/v1/stock/{id}/reorder-point/ — admin only, and
critically, must never be able to touch quantity.
"""
import pytest
from decimal import Decimal

from tests.factories import StockFactory


@pytest.mark.django_db
class TestStockReorderPointUpdate:
    def test_unauthenticated_returns_401(self, api_client):
        stock = StockFactory()
        response = api_client.patch(
            f"/api/v1/stock/{stock.id}/reorder-point/", {"reorder_point": "10"}
        )
        assert response.status_code == 401

    def test_seller_cannot_update_reorder_point(self, seller_client):
        client, user, branch = seller_client
        stock = StockFactory(branch=branch)

        response = client.patch(
            f"/api/v1/stock/{stock.id}/reorder-point/", {"reorder_point": "10"}
        )

        assert response.status_code == 403

    def test_admin_sets_reorder_point(self, admin_client):
        client, _ = admin_client
        stock = StockFactory(quantity=Decimal("50"))

        response = client.patch(
            f"/api/v1/stock/{stock.id}/reorder-point/", {"reorder_point": "15"}
        )

        assert response.status_code == 200
        assert Decimal(response.data["reorder_point"]) == Decimal("15.000")

    def test_update_never_touches_quantity(self, admin_client):
        client, _ = admin_client
        stock = StockFactory(quantity=Decimal("50"))

        response = client.patch(
            f"/api/v1/stock/{stock.id}/reorder-point/", {"reorder_point": "15"}
        )

        assert Decimal(response.data["quantity"]) == Decimal("50.000")

    def test_null_clears_reorder_point(self, admin_client):
        client, _ = admin_client
        stock = StockFactory(reorder_point=Decimal("10"))

        response = client.patch(
            f"/api/v1/stock/{stock.id}/reorder-point/", {"reorder_point": None}
        )

        assert response.status_code == 200
        assert response.data["reorder_point"] is None

    def test_negative_reorder_point_rejected(self, admin_client):
        client, _ = admin_client
        stock = StockFactory()

        response = client.patch(
            f"/api/v1/stock/{stock.id}/reorder-point/", {"reorder_point": "-5"}
        )

        assert response.status_code == 400

    def test_unknown_stock_row_returns_404(self, admin_client):
        client, _ = admin_client
        response = client.patch(
            "/api/v1/stock/999999/reorder-point/", {"reorder_point": "10"}
        )
        assert response.status_code == 404
