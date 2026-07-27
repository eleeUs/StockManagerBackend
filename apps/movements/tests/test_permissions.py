"""
tests/test_permissions.py

Each test in this file maps to a specific rule in BUSINESS_RULES.md.
The section reference is noted in each docstring.

These tests are integration-level: they go through the full HTTP stack
(serializer → view → service → DB) to verify that the permission layer
cannot be bypassed at any point.

Run: pytest apps/movements/tests/test_permissions.py -v
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
)
from apps.movements.models import MovementStatus


# ---------------------------------------------------------------------------
# 1. Unauthenticated access → 401 on every endpoint
# BUSINESS_RULES §1 (implicit): authentication is required
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestUnauthenticated:

    ENDPOINTS = [
        ("GET",  "/api/v1/stock/"),
        ("GET",  "/api/v1/movements/"),
        ("POST", "/api/v1/movements/ingreso/"),
        ("POST", "/api/v1/movements/venta/"),
        ("POST", "/api/v1/movements/transferencia/"),
        ("POST", "/api/v1/movements/ajuste/"),
        ("POST", "/api/v1/movements/devolucion/"),
        ("POST", "/api/v1/movements/donacion/"),
        ("GET",  "/api/v1/users/"),
    ]

    @pytest.mark.parametrize("method,url", ENDPOINTS)
    def test_unauthenticated_returns_401(self, api_client, method, url):
        """BUSINESS_RULES §1: all endpoints require authentication."""
        response = getattr(api_client, method.lower())(url, format="json")
        assert response.status_code == 401, (
            f"{method} {url} should return 401 for unauthenticated requests"
        )


# ---------------------------------------------------------------------------
# 2. Seller permissions
# BUSINESS_RULES §1.2
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSellerPermissions:

    def test_seller_can_sell_from_own_branch(self, seller_client, product):
        """BUSINESS_RULES §1.2: seller can sell from their assigned branch."""
        client, user, branch = seller_client
        StockFactory(product=product, branch=branch, quantity=Decimal("10"))

        response = client.post("/api/v1/movements/venta/", {
            "product":  product.id,
            "branch":   branch.id,
            "quantity": "3.000",
        }, format="json")

        assert response.status_code == 201
        assert response.data["movement_type"] == "venta"

    def test_seller_cannot_sell_from_other_branch(self, seller_client, product):
        """BUSINESS_RULES §1.2: seller is restricted to their assigned branch."""
        client, user, branch = seller_client
        other_branch = BranchFactory()
        StockFactory(product=product, branch=other_branch, quantity=Decimal("10"))

        response = client.post("/api/v1/movements/venta/", {
            "product":  product.id,
            "branch":   other_branch.id,
            "quantity": "1.000",
        }, format="json")

        assert response.status_code == 403
        assert response.data["error"] == "unauthorized_movement"

    def test_seller_can_read_stock_from_any_branch(self, seller_client, product):
        """BUSINESS_RULES §1.2: sellers have global READ visibility on stock."""
        client, user, branch = seller_client
        other_branch = BranchFactory()
        StockFactory(product=product, branch=other_branch, quantity=Decimal("5"))

        response = client.get("/api/v1/stock/", format="json")

        assert response.status_code == 200
        branch_ids = {item["branch"] for item in response.data["results"]}
        assert other_branch.id in branch_ids

    def test_seller_cannot_create_ingreso(self, seller_client, product):
        """BUSINESS_RULES §1.2: only admins can register stock entries."""
        client, user, branch = seller_client

        response = client.post("/api/v1/movements/ingreso/", {
            "product":    product.id,
            "branch":     branch.id,
            "quantity":   "10.000",
            "entry_date": "2026-01-01",
        }, format="json")

        assert response.status_code == 403

    def test_seller_cannot_create_transferencia(self, seller_client, product):
        """BUSINESS_RULES §1.2: only admins can create transfers."""
        client, user, branch = seller_client
        other_branch = BranchFactory()
        StockFactory(product=product, branch=branch, quantity=Decimal("10"))

        response = client.post("/api/v1/movements/transferencia/", {
            "product":           product.id,
            "source_branch":     branch.id,
            "destination_branch": other_branch.id,
            "quantity":          "5.000",
        }, format="json")

        assert response.status_code == 403

    def test_seller_cannot_create_ajuste(self, seller_client, product):
        """BUSINESS_RULES §1.2: only admins can adjust stock."""
        client, user, branch = seller_client
        StockFactory(product=product, branch=branch, quantity=Decimal("10"))

        response = client.post("/api/v1/movements/ajuste/", {
            "product":      product.id,
            "branch":       branch.id,
            "new_quantity": "20.000",
        }, format="json")

        assert response.status_code == 403

    def test_seller_cannot_create_devolucion(self, seller_client, product):
        """BUSINESS_RULES §1.2: only admins can register returns."""
        client, user, branch = seller_client
        StockFactory(product=product, branch=branch, quantity=Decimal("10"))

        response = client.post("/api/v1/movements/devolucion/", {
            "product":  product.id,
            "branch":   branch.id,
            "quantity": "1.000",
        }, format="json")

        assert response.status_code == 403

    def test_seller_cannot_create_donacion(self, seller_client, product):
        """BUSINESS_RULES §1.2: only admins can register donations."""
        client, user, branch = seller_client
        StockFactory(product=product, branch=branch, quantity=Decimal("10"))

        response = client.post("/api/v1/movements/donacion/", {
            "product":  product.id,
            "branch":   branch.id,
            "quantity": "1.000",
        }, format="json")

        assert response.status_code == 403

    def test_seller_cannot_manage_users(self, seller_client):
        """BUSINESS_RULES §1.2: sellers cannot access user management."""
        client, user, branch = seller_client

        response = client.get("/api/v1/users/", format="json")

        assert response.status_code == 403

    def test_seller_cannot_retrieve_other_user(self, seller_client):
        """BUSINESS_RULES §1.2: sellers cannot view other users' profiles."""
        client, user, branch = seller_client
        other_seller = SellerFactory(branch=BranchFactory())

        response = client.get(f"/api/v1/users/{other_seller.id}/", format="json")

        assert response.status_code == 403

    def test_seller_can_retrieve_own_profile(self, seller_client):
        """Sellers can always access their own profile via /auth/me/."""
        client, user, branch = seller_client

        response = client.get("/api/v1/auth/me/", format="json")

        assert response.status_code == 200
        assert response.data["email"] == user.email


# ---------------------------------------------------------------------------
# 3. Movement history scoping
# BUSINESS_RULES §7
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestMovementHistoryScoping:

    def test_seller_sees_own_branch_outgoing_movements(self, seller_client, product):
        """BUSINESS_RULES §7: sellers see movements where their branch is source."""
        client, user, branch = seller_client
        # Movement at seller's branch
        StockMovementFactory(
            product=product,
            source_branch=branch,
            created_by=AdminFactory(),
        )
        # Movement at another branch — should NOT appear
        StockMovementFactory(
            product=product,
            source_branch=BranchFactory(),
            created_by=AdminFactory(),
        )

        response = client.get("/api/v1/movements/", format="json")

        assert response.status_code == 200
        movement_ids = [m["source_branch"] for m in response.data["results"]]
        assert all(bid == branch.id for bid in movement_ids)

    def test_seller_sees_own_branch_incoming_movements(self, seller_client, product):
        """BUSINESS_RULES §7: sellers see incoming transfers to their branch."""
        from apps.movements.models import MovementType
        client, user, branch = seller_client
        # Incoming transfer to seller's branch
        StockMovementFactory(
            product=product,
            movement_type=MovementType.TRANSFERENCIA,
            source_branch=BranchFactory(),
            destination_branch=branch,
            created_by=AdminFactory(),
        )

        response = client.get("/api/v1/movements/", format="json")

        assert response.status_code == 200
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["destination_branch"] == branch.id

    def test_seller_does_not_see_other_branch_movements(self, seller_client, product):
        """BUSINESS_RULES §7: sellers cannot access movements from other branches."""
        client, user, branch = seller_client
        other_branch = BranchFactory()
        # Movement between two other branches — seller should not see it
        StockMovementFactory(
            product=product,
            source_branch=other_branch,
            created_by=AdminFactory(),
        )

        response = client.get("/api/v1/movements/", format="json")

        assert response.status_code == 200
        assert len(response.data["results"]) == 0

    def test_admin_sees_all_movements(self, admin_client, product):
        """BUSINESS_RULES §7: admins see the full movement history."""
        client, admin = admin_client
        branch_a = BranchFactory()
        branch_b = BranchFactory()
        StockMovementFactory(product=product, source_branch=branch_a, created_by=admin)
        StockMovementFactory(product=product, source_branch=branch_b, created_by=admin)

        response = client.get("/api/v1/movements/", format="json")

        assert response.status_code == 200
        assert len(response.data["results"]) == 2


# ---------------------------------------------------------------------------
# 4. Admin permissions
# BUSINESS_RULES §1.3
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAdminPermissions:

    def test_admin_can_create_ingreso(self, admin_client, product):
        """BUSINESS_RULES §1.3: admins can perform all movement types."""
        client, admin = admin_client
        branch = BranchFactory()

        response = client.post("/api/v1/movements/ingreso/", {
            "product":    product.id,
            "branch":     branch.id,
            "quantity":   "20.000",
            "entry_date": "2026-01-01",
        }, format="json")

        assert response.status_code == 201

    def test_admin_can_sell_from_any_branch(self, admin_client, product):
        """BUSINESS_RULES §1.3: admins can sell from any branch."""
        client, admin = admin_client
        branch = BranchFactory()
        StockFactory(product=product, branch=branch, quantity=Decimal("10"))

        response = client.post("/api/v1/movements/venta/", {
            "product":  product.id,
            "branch":   branch.id,
            "quantity": "3.000",
        }, format="json")

        assert response.status_code == 201

    def test_admin_can_create_transfer_and_confirm(self, admin_client, two_branches_with_stock):
        """BUSINESS_RULES §1.3 + §3.3: admin creates and confirms transfer."""
        client, admin = admin_client
        product, branch_a, branch_b = two_branches_with_stock

        # Step 1: create
        create_response = client.post("/api/v1/movements/transferencia/", {
            "product":            product.id,
            "source_branch":      branch_a.id,
            "destination_branch": branch_b.id,
            "quantity":           "10.000",
        }, format="json")
        assert create_response.status_code == 201
        assert create_response.data["status"] == MovementStatus.PENDING

        # Step 2: confirm
        movement_id = create_response.data["id"]
        confirm_response = client.post(
            f"/api/v1/movements/transferencia/{movement_id}/confirm/",
            format="json",
        )
        assert confirm_response.status_code == 200
        assert confirm_response.data["status"] == MovementStatus.CONFIRMED

    def test_admin_can_list_all_users(self, admin_client):
        """BUSINESS_RULES §1.3: admins can manage users."""
        client, admin = admin_client
        SellerFactory()  # another user
        SellerFactory()  # another user

        response = client.get("/api/v1/users/", format="json")

        assert response.status_code == 200
        # At minimum the 2 sellers + the admin itself
        assert response.data["count"] >= 3

    def test_admin_can_create_user(self, admin_client):
        """BUSINESS_RULES §1.3: admins can create users."""
        client, admin = admin_client
        branch = BranchFactory()

        response = client.post("/api/v1/users/", {
            "email":     "newseller@test.com",
            "full_name": "New Seller",
            "role":      "seller",
            "branch":    branch.id,
            "password":  "securepassword123",
        }, format="json")

        assert response.status_code == 201
        assert response.data["role"] == "seller"

    def test_admin_can_deactivate_user(self, admin_client):
        """BUSINESS_RULES §1.3: admins can deactivate users."""
        client, admin = admin_client
        seller = SellerFactory()

        response = client.patch(f"/api/v1/users/{seller.id}/", {
            "is_active": False,
        }, format="json")

        assert response.status_code == 200
        assert response.data["is_active"] is False


# ---------------------------------------------------------------------------
# 5. Transfer two-step flow edge cases
# BUSINESS_RULES §3.3
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTransferFlowPermissions:

    def test_cannot_confirm_already_confirmed_transfer(self, admin_client, two_branches_with_stock):
        """BUSINESS_RULES §3.3: a confirmed transfer cannot be confirmed again."""
        client, admin = admin_client
        product, branch_a, branch_b = two_branches_with_stock

        create = client.post("/api/v1/movements/transferencia/", {
            "product":            product.id,
            "source_branch":      branch_a.id,
            "destination_branch": branch_b.id,
            "quantity":           "5.000",
        }, format="json")
        movement_id = create.data["id"]

        client.post(f"/api/v1/movements/transferencia/{movement_id}/confirm/", format="json")
        second_confirm = client.post(
            f"/api/v1/movements/transferencia/{movement_id}/confirm/",
            format="json",
        )

        assert second_confirm.status_code == 409
        assert second_confirm.data["error"] == "transfer_already_confirmed"

    def test_cannot_cancel_confirmed_transfer(self, admin_client, two_branches_with_stock):
        """BUSINESS_RULES §3.3 + §5: confirmed transfers must be reversed, not cancelled."""
        client, admin = admin_client
        product, branch_a, branch_b = two_branches_with_stock

        create = client.post("/api/v1/movements/transferencia/", {
            "product":            product.id,
            "source_branch":      branch_a.id,
            "destination_branch": branch_b.id,
            "quantity":           "5.000",
        }, format="json")
        movement_id = create.data["id"]

        client.post(f"/api/v1/movements/transferencia/{movement_id}/confirm/", format="json")
        cancel = client.post(
            f"/api/v1/movements/transferencia/{movement_id}/cancel/",
            format="json",
        )

        assert cancel.status_code == 409
        assert cancel.data["error"] == "transfer_already_confirmed"

    def test_seller_cannot_confirm_transfer(self, seller_client, two_branches_with_stock):
        """BUSINESS_RULES §1.2: sellers cannot interact with transfers at all."""
        client, user, branch = seller_client
        product, branch_a, branch_b = two_branches_with_stock
        pending = StockMovementFactory(
            product=product,
            source_branch=branch_a,
            destination_branch=branch_b,
            created_by=AdminFactory(),
        )

        response = client.post(
            f"/api/v1/movements/transferencia/{pending.id}/confirm/",
            format="json",
        )

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# 6. User role integrity
# BUSINESS_RULES §1.1
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestUserRoleIntegrity:

    def test_creating_seller_without_branch_returns_400(self, admin_client):
        """BUSINESS_RULES §1.2: sellers must have a branch assigned."""
        client, admin = admin_client

        response = client.post("/api/v1/users/", {
            "email":     "branchless@test.com",
            "full_name": "Branchless Seller",
            "role":      "seller",
            "password":  "password123",
            # no branch
        }, format="json")

        assert response.status_code == 400
        assert "branch" in response.data

    def test_creating_admin_with_branch_returns_400(self, admin_client):
        """BUSINESS_RULES §1.3: admins must not be assigned to a branch."""
        client, admin = admin_client
        branch = BranchFactory()

        response = client.post("/api/v1/users/", {
            "email":     "branchedadmin@test.com",
            "full_name": "Branched Admin",
            "role":      "admin",
            "branch":    branch.id,
            "password":  "password123",
        }, format="json")

        assert response.status_code == 400
        assert "branch" in response.data
