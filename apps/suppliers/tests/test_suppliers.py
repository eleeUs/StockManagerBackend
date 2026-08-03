"""
apps/suppliers/tests/test_suppliers.py

CRUD + permission tests for Supplier, following the same pattern as
Branch (list/detail, admin-only writes, seller sees active only).
"""
import pytest

from tests.factories import SupplierFactory


@pytest.mark.django_db
class TestSupplierList:
    def test_unauthenticated_returns_401(self, api_client):
        response = api_client.get("/api/v1/suppliers/")
        assert response.status_code == 401

    def test_admin_sees_inactive_suppliers(self, admin_client):
        client, _ = admin_client
        SupplierFactory(is_active=False)

        response = client.get("/api/v1/suppliers/")

        assert response.status_code == 200
        assert any(not s["is_active"] for s in response.data["results"])

    def test_seller_only_sees_active_suppliers(self, seller_client):
        client, user, branch = seller_client
        SupplierFactory(is_active=True)
        SupplierFactory(is_active=False)

        response = client.get("/api/v1/suppliers/")

        assert response.status_code == 200
        assert all(s["is_active"] for s in response.data["results"])


@pytest.mark.django_db
class TestSupplierCreate:
    def test_admin_can_create_supplier(self, admin_client):
        client, _ = admin_client
        payload = {"name": "Acme Distribution", "contact_email": "sales@acme.test"}

        response = client.post("/api/v1/suppliers/", payload)

        assert response.status_code == 201
        assert response.data["name"] == "Acme Distribution"

    def test_seller_cannot_create_supplier(self, seller_client):
        client, user, branch = seller_client
        response = client.post("/api/v1/suppliers/", {"name": "Acme Distribution"})
        assert response.status_code == 403


@pytest.mark.django_db
class TestSupplierUpdate:
    def test_admin_can_deactivate_supplier(self, admin_client):
        client, _ = admin_client
        supplier = SupplierFactory(is_active=True)

        response = client.patch(f"/api/v1/suppliers/{supplier.id}/", {"is_active": False})

        assert response.status_code == 200
        assert response.data["is_active"] is False

    def test_seller_cannot_update_supplier(self, seller_client):
        client, user, branch = seller_client
        supplier = SupplierFactory()

        response = client.patch(f"/api/v1/suppliers/{supplier.id}/", {"is_active": False})

        assert response.status_code == 403
