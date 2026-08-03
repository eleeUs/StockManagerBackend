"""
apps/reports/tests/test_reports.py

Covers the three read-only reporting endpoints introduced in Phase 6:
happy path, threshold filtering, date filtering, admin-only access,
and seller branch scoping.

Test data comes exclusively from tests/factories.py, per project convention.
StockMovementFactory is used directly (not the service layer) because these
are read-only tests — see tests/factories.py docstring.
"""
import pytest
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from tests.factories import BranchFactory, StockFactory, StockMovementFactory
from apps.movements.models import MovementType, StockMovement


# ---------------------------------------------------------------------------
# A1 — Low stock report
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestLowStockReport:
    """GET /api/v1/reports/stock/low/"""

    def test_unauthenticated_returns_401(self, api_client):
        response = api_client.get("/api/v1/reports/stock/low/")
        assert response.status_code == 401

    def test_default_threshold_excludes_rows_above_ten(self, admin_client):
        client, _ = admin_client
        branch = BranchFactory()
        StockFactory(branch=branch, quantity=Decimal("5"))
        StockFactory(branch=branch, quantity=Decimal("50"))

        response = client.get("/api/v1/reports/stock/low/")

        assert response.status_code == 200
        quantities = [Decimal(row["quantity"]) for row in response.data["results"]]
        assert all(q <= 10 for q in quantities)
        assert any(q == Decimal("5.000") for q in quantities)

    def test_custom_threshold_includes_higher_rows(self, admin_client):
        client, _ = admin_client
        branch = BranchFactory()
        StockFactory(branch=branch, quantity=Decimal("15"))

        response = client.get("/api/v1/reports/stock/low/", {"threshold": 20})

        assert response.status_code == 200
        quantities = [Decimal(row["quantity"]) for row in response.data["results"]]
        assert Decimal("15.000") in quantities

    def test_admin_sees_all_branches(self, admin_client):
        client, _ = admin_client
        branch_a = BranchFactory()
        branch_b = BranchFactory()
        StockFactory(branch=branch_a, quantity=Decimal("1"))
        StockFactory(branch=branch_b, quantity=Decimal("1"))

        response = client.get("/api/v1/reports/stock/low/", {"threshold": 10})

        branch_ids = {row["branch"] for row in response.data["results"]}
        assert branch_a.id in branch_ids
        assert branch_b.id in branch_ids

    def test_seller_scoped_to_own_branch(self, seller_client):
        client, user, branch = seller_client
        other_branch = BranchFactory()
        StockFactory(branch=branch, quantity=Decimal("1"))
        StockFactory(branch=other_branch, quantity=Decimal("1"))

        response = client.get("/api/v1/reports/stock/low/", {"threshold": 10})

        assert response.status_code == 200
        branch_ids = {row["branch"] for row in response.data["results"]}
        assert branch_ids == {branch.id}


# ---------------------------------------------------------------------------
# A2 — Movement summary report
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestMovementSummaryReport:
    """GET /api/v1/reports/movements/summary/"""

    def test_unauthenticated_returns_401(self, api_client):
        response = api_client.get(
            "/api/v1/reports/movements/summary/",
            {"date_from": "2026-01-01", "date_to": "2026-01-31"},
        )
        assert response.status_code == 401

    def test_seller_cannot_access(self, seller_client):
        client, user, branch = seller_client
        response = client.get(
            "/api/v1/reports/movements/summary/",
            {"date_from": "2026-01-01", "date_to": "2026-01-31"},
        )
        assert response.status_code == 403

    def test_missing_date_params_returns_400(self, admin_client):
        client, _ = admin_client
        response = client.get("/api/v1/reports/movements/summary/")
        assert response.status_code == 400

    def test_aggregates_count_and_total_quantity_per_type(self, admin_client):
        client, _ = admin_client
        StockMovementFactory(movement_type=MovementType.VENTA, quantity=Decimal("10"))
        StockMovementFactory(movement_type=MovementType.VENTA, quantity=Decimal("5"))

        today = date.today().isoformat()
        response = client.get(
            "/api/v1/reports/movements/summary/",
            {"date_from": today, "date_to": today},
        )

        assert response.status_code == 200
        venta_row = next(r for r in response.data["results"] if r["movement_type"] == "venta")
        assert venta_row["count"] == 2
        assert Decimal(venta_row["total_quantity"]) == Decimal("15.000")

    def test_date_range_excludes_movements_outside_window(self, admin_client):
        client, _ = admin_client
        old_movement = StockMovementFactory(movement_type=MovementType.DONACION, quantity=Decimal("3"))
        # auto_now_add only fires on INSERT — safe to backdate via update().
        StockMovement.objects.filter(pk=old_movement.pk).update(
            created_at=timezone.now() - timedelta(days=30)
        )

        today = date.today().isoformat()
        response = client.get(
            "/api/v1/reports/movements/summary/",
            {"date_from": today, "date_to": today},
        )

        types = [r["movement_type"] for r in response.data["results"]]
        assert "donacion" not in types


# ---------------------------------------------------------------------------
# A3 — Branch activity report
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestBranchActivityReport:
    """GET /api/v1/reports/branches/{id}/activity/"""

    def test_unauthenticated_returns_401(self, api_client):
        branch = BranchFactory()
        response = api_client.get(
            f"/api/v1/reports/branches/{branch.id}/activity/",
            {"date_from": "2026-01-01", "date_to": "2026-01-31"},
        )
        assert response.status_code == 401

    def test_seller_cannot_access(self, seller_client):
        client, user, branch = seller_client
        response = client.get(
            f"/api/v1/reports/branches/{branch.id}/activity/",
            {"date_from": "2026-01-01", "date_to": "2026-01-31"},
        )
        assert response.status_code == 403

    def test_missing_date_params_returns_400(self, admin_client):
        client, _ = admin_client
        branch = BranchFactory()
        response = client.get(f"/api/v1/reports/branches/{branch.id}/activity/")
        assert response.status_code == 400

    def test_unknown_branch_returns_404(self, admin_client):
        client, _ = admin_client
        response = client.get(
            "/api/v1/reports/branches/999999/activity/",
            {"date_from": "2026-01-01", "date_to": "2026-01-31"},
        )
        assert response.status_code == 404

    def test_returns_summary_and_daily_breakdown(self, admin_client):
        client, _ = admin_client
        branch = BranchFactory()
        StockMovementFactory(
            movement_type=MovementType.VENTA,
            source_branch=branch,
            destination_branch=None,
            quantity=Decimal("7"),
        )

        today = date.today().isoformat()
        response = client.get(
            f"/api/v1/reports/branches/{branch.id}/activity/",
            {"date_from": today, "date_to": today},
        )

        assert response.status_code == 200
        assert response.data["branch_id"] == branch.id
        assert response.data["branch_name"] == branch.name
        assert len(response.data["daily_breakdown"]) == 1
        assert response.data["daily_breakdown"][0]["movement_type"] == "venta"

    def test_activity_excludes_other_branches(self, admin_client):
        client, _ = admin_client
        branch = BranchFactory()
        other_branch = BranchFactory()
        StockMovementFactory(
            movement_type=MovementType.VENTA,
            source_branch=other_branch,
            destination_branch=None,
        )

        today = date.today().isoformat()
        response = client.get(
            f"/api/v1/reports/branches/{branch.id}/activity/",
            {"date_from": today, "date_to": today},
        )

        assert response.data["summary_by_type"] == []
        assert response.data["daily_breakdown"] == []
