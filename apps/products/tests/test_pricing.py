"""
apps/products/tests/test_pricing.py

Covers cost_price/sale_price on Product: validation, and the role-based
visibility rule (cost_price hidden from sellers) added in Phase 7.
"""
import pytest
from decimal import Decimal

from tests.factories import ProductFactory


@pytest.mark.django_db
class TestProductPricingVisibility:
    def test_admin_sees_cost_price(self, admin_client):
        client, _ = admin_client
        product = ProductFactory(cost_price=Decimal("10.00"), sale_price=Decimal("15.00"))

        response = client.get(f"/api/v1/products/{product.id}/")

        assert response.status_code == 200
        assert "cost_price" in response.data
        assert Decimal(response.data["cost_price"]) == Decimal("10.00")

    def test_seller_does_not_see_cost_price(self, seller_client):
        client, user, branch = seller_client
        product = ProductFactory(cost_price=Decimal("10.00"), sale_price=Decimal("15.00"))

        response = client.get(f"/api/v1/products/{product.id}/")

        assert response.status_code == 200
        assert "cost_price" not in response.data

    def test_seller_sees_sale_price(self, seller_client):
        client, user, branch = seller_client
        product = ProductFactory(sale_price=Decimal("15.00"))

        response = client.get(f"/api/v1/products/{product.id}/")

        assert response.status_code == 200
        assert Decimal(response.data["sale_price"]) == Decimal("15.00")

    def test_cost_price_hidden_in_list_view_too(self, seller_client):
        client, user, branch = seller_client
        ProductFactory(cost_price=Decimal("10.00"))

        response = client.get("/api/v1/products/")

        assert response.status_code == 200
        assert all("cost_price" not in row for row in response.data["results"])


@pytest.mark.django_db
class TestProductPricingValidation:
    def test_negative_cost_price_rejected(self, admin_client):
        client, _ = admin_client
        response = client.post(
            "/api/v1/products/",
            {"sku": "NEG-001", "name": "Bad Product", "cost_price": "-1.00"},
        )
        assert response.status_code == 400

    def test_product_without_prices_is_still_valid(self, admin_client):
        client, _ = admin_client
        response = client.post(
            "/api/v1/products/",
            {"sku": "NOPRICE-001", "name": "No Price Yet"},
        )
        assert response.status_code == 201
        assert response.data["cost_price"] is None
