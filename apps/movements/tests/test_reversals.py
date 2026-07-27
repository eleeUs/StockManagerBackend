"""
tests/test_reversals.py

Tests for the reversal service and endpoint.
Each confirmed movement type has a happy-path test and an error test.
Edge cases (already reversed, pending transfer, chain prevention) are
grouped at the bottom.

Run: pytest apps/movements/tests/test_reversals.py -v
"""
import pytest
from decimal import Decimal

from tests.factories import (
    AdminFactory,
    BranchFactory,
    ProductFactory,
    StockFactory,
)
from apps.movements.models import MovementType, MovementStatus
from apps.movements.services import StockMovementService
from apps.stock.models import Stock
from core.exceptions import InsufficientStockError, InvalidMovementError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def stock_qty(product, branch) -> Decimal:
    return Stock.objects.get(product=product, branch=branch).quantity


# ---------------------------------------------------------------------------
# INGRESO reversal
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestReverseIngreso:

    def setup_method(self):
        self.admin   = AdminFactory()
        self.branch  = BranchFactory()
        self.product = ProductFactory()

    def test_reverse_ingreso_decrements_stock(self):
        """Reversing an entry removes the entered quantity from the branch."""
        movement = StockMovementService.ingreso(
            product_id=self.product.id,
            branch_id=self.branch.id,
            quantity=Decimal("20"),
            entry_date="2026-01-01",
            user=self.admin,
        )
        assert stock_qty(self.product, self.branch) == Decimal("20")

        reversal = StockMovementService.revertir(
            movement_id=movement.id,
            user=self.admin,
        )

        assert stock_qty(self.product, self.branch) == Decimal("0")
        assert reversal.movement_type == MovementType.REVERSAL
        assert reversal.status == MovementStatus.CONFIRMED
        assert reversal.reverses_movement_id == movement.id

    def test_reverse_ingreso_insufficient_stock_raises(self):
        """
        Cannot reverse an ingreso if stock at that branch is now lower than
        the original quantity (e.g. some was sold in the meantime).
        """
        movement = StockMovementService.ingreso(
            product_id=self.product.id,
            branch_id=self.branch.id,
            quantity=Decimal("10"),
            entry_date="2026-01-01",
            user=self.admin,
        )
        # Sell some so we no longer have 10
        StockMovementService.venta(
            product_id=self.product.id,
            branch_id=self.branch.id,
            quantity=Decimal("5"),
            user=self.admin,
        )
        assert stock_qty(self.product, self.branch) == Decimal("5")

        with pytest.raises(InsufficientStockError):
            StockMovementService.revertir(movement_id=movement.id, user=self.admin)

        # Stock should be unchanged
        assert stock_qty(self.product, self.branch) == Decimal("5")


# ---------------------------------------------------------------------------
# VENTA reversal
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestReverseVenta:

    def setup_method(self):
        self.admin   = AdminFactory()
        self.branch  = BranchFactory()
        self.product = ProductFactory()
        StockFactory(product=self.product, branch=self.branch, quantity=Decimal("15"))

    def test_reverse_venta_restores_stock(self):
        """Reversing a sale adds stock back to the source branch."""
        movement = StockMovementService.venta(
            product_id=self.product.id,
            branch_id=self.branch.id,
            quantity=Decimal("7"),
            user=self.admin,
        )
        assert stock_qty(self.product, self.branch) == Decimal("8")

        reversal = StockMovementService.revertir(
            movement_id=movement.id,
            user=self.admin,
        )

        assert stock_qty(self.product, self.branch) == Decimal("15")
        assert reversal.reverses_movement_id == movement.id
        assert reversal.destination_branch == self.branch

    def test_reverse_venta_creates_movement_record(self):
        """The reversal must be persisted as a REVERSAL movement."""
        movement = StockMovementService.venta(
            product_id=self.product.id,
            branch_id=self.branch.id,
            quantity=Decimal("3"),
            user=self.admin,
        )
        reversal = StockMovementService.revertir(movement_id=movement.id, user=self.admin)

        from apps.movements.models import StockMovement
        assert StockMovement.objects.filter(
            movement_type=MovementType.REVERSAL,
            reverses_movement=movement,
        ).exists()


# ---------------------------------------------------------------------------
# TRANSFERENCIA reversal
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestReverseTransferencia:

    def setup_method(self):
        self.admin    = AdminFactory()
        self.branch_a = BranchFactory()
        self.branch_b = BranchFactory()
        self.product  = ProductFactory()
        StockFactory(product=self.product, branch=self.branch_a, quantity=Decimal("30"))
        StockFactory(product=self.product, branch=self.branch_b, quantity=Decimal("0"))

    def test_reverse_confirmed_transfer_moves_stock_back(self):
        """Reversing a transfer returns stock from destination to source."""
        transfer = StockMovementService.crear_transferencia(
            product_id=self.product.id,
            source_branch_id=self.branch_a.id,
            destination_branch_id=self.branch_b.id,
            quantity=Decimal("10"),
            user=self.admin,
        )
        StockMovementService.confirmar_transferencia(
            movement_id=transfer.id, user=self.admin
        )
        assert stock_qty(self.product, self.branch_a) == Decimal("20")
        assert stock_qty(self.product, self.branch_b) == Decimal("10")

        StockMovementService.revertir(movement_id=transfer.id, user=self.admin)

        assert stock_qty(self.product, self.branch_a) == Decimal("30")
        assert stock_qty(self.product, self.branch_b) == Decimal("0")

    def test_reverse_pending_transfer_raises(self):
        """
        Pending transfers must be cancelled, not reversed.
        BUSINESS_RULES §5
        """
        transfer = StockMovementService.crear_transferencia(
            product_id=self.product.id,
            source_branch_id=self.branch_a.id,
            destination_branch_id=self.branch_b.id,
            quantity=Decimal("5"),
            user=self.admin,
        )
        assert transfer.status == MovementStatus.PENDING

        with pytest.raises(InvalidMovementError, match="cancel"):
            StockMovementService.revertir(movement_id=transfer.id, user=self.admin)

    def test_reverse_transfer_insufficient_dest_stock_raises(self):
        """
        If someone already sold the stock that arrived at destination,
        the reversal fails with InsufficientStockError.
        """
        transfer = StockMovementService.crear_transferencia(
            product_id=self.product.id,
            source_branch_id=self.branch_a.id,
            destination_branch_id=self.branch_b.id,
            quantity=Decimal("10"),
            user=self.admin,
        )
        StockMovementService.confirmar_transferencia(
            movement_id=transfer.id, user=self.admin
        )
        # Sell everything that arrived
        StockMovementService.venta(
            product_id=self.product.id,
            branch_id=self.branch_b.id,
            quantity=Decimal("10"),
            user=self.admin,
        )

        with pytest.raises(InsufficientStockError):
            StockMovementService.revertir(movement_id=transfer.id, user=self.admin)


# ---------------------------------------------------------------------------
# AJUSTE reversal
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestReverseAjuste:

    def setup_method(self):
        self.admin   = AdminFactory()
        self.branch  = BranchFactory()
        self.product = ProductFactory()
        StockFactory(product=self.product, branch=self.branch, quantity=Decimal("10"))

    def test_reverse_ajuste_restores_previous_quantity(self):
        """Reversing an adjustment restores stock to what it was before."""
        adjustment = StockMovementService.ajuste(
            product_id=self.product.id,
            branch_id=self.branch.id,
            new_quantity=Decimal("50"),
            user=self.admin,
        )
        assert stock_qty(self.product, self.branch) == Decimal("50")
        assert adjustment.adjustment_previous_quantity == Decimal("10")

        StockMovementService.revertir(movement_id=adjustment.id, user=self.admin)

        assert stock_qty(self.product, self.branch) == Decimal("10")

    def test_reverse_ajuste_to_zero_restores_previous(self):
        """Reversing a zero-adjustment restores the stock that was there before."""
        adjustment = StockMovementService.ajuste(
            product_id=self.product.id,
            branch_id=self.branch.id,
            new_quantity=Decimal("0"),
            user=self.admin,
            notes="Write-off",
        )
        assert stock_qty(self.product, self.branch) == Decimal("0")

        StockMovementService.revertir(movement_id=adjustment.id, user=self.admin)

        assert stock_qty(self.product, self.branch) == Decimal("10")


# ---------------------------------------------------------------------------
# DONACION reversal
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestReverseDonacion:

    def setup_method(self):
        self.admin   = AdminFactory()
        self.branch  = BranchFactory()
        self.product = ProductFactory()
        StockFactory(product=self.product, branch=self.branch, quantity=Decimal("20"))

    def test_reverse_donacion_restores_stock(self):
        """Reversing a donation adds stock back to the source branch."""
        donation = StockMovementService.donacion(
            product_id=self.product.id,
            branch_id=self.branch.id,
            quantity=Decimal("8"),
            user=self.admin,
        )
        assert stock_qty(self.product, self.branch) == Decimal("12")

        StockMovementService.revertir(movement_id=donation.id, user=self.admin)

        assert stock_qty(self.product, self.branch) == Decimal("20")


# ---------------------------------------------------------------------------
# DEVOLUCION reversal
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestReverseDevolucion:

    def setup_method(self):
        self.admin   = AdminFactory()
        self.branch  = BranchFactory()
        self.product = ProductFactory()
        StockFactory(product=self.product, branch=self.branch, quantity=Decimal("10"))

    def test_reverse_devolucion_removes_returned_stock(self):
        """Reversing a return removes the returned quantity from the branch."""
        devolucion = StockMovementService.devolucion(
            product_id=self.product.id,
            branch_id=self.branch.id,
            quantity=Decimal("4"),
            user=self.admin,
        )
        assert stock_qty(self.product, self.branch) == Decimal("14")

        StockMovementService.revertir(movement_id=devolucion.id, user=self.admin)

        assert stock_qty(self.product, self.branch) == Decimal("10")


# ---------------------------------------------------------------------------
# Edge cases — shared across all types
# BUSINESS_RULES §5
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestReversalEdgeCases:

    def setup_method(self):
        self.admin   = AdminFactory()
        self.branch  = BranchFactory()
        self.product = ProductFactory()
        StockFactory(product=self.product, branch=self.branch, quantity=Decimal("20"))

    def test_cannot_reverse_same_movement_twice(self):
        """
        A movement already reversed cannot be reversed again.
        The OneToOneField on reverses_movement enforces this at the DB level,
        but we validate early for a clear error message.
        """
        movement = StockMovementService.venta(
            product_id=self.product.id,
            branch_id=self.branch.id,
            quantity=Decimal("5"),
            user=self.admin,
        )
        StockMovementService.revertir(movement_id=movement.id, user=self.admin)

        with pytest.raises(InvalidMovementError, match="already been reversed"):
            StockMovementService.revertir(movement_id=movement.id, user=self.admin)

    def test_cannot_reverse_a_reversal(self):
        """
        Reversals cannot themselves be reversed — no infinite chains.
        BUSINESS_RULES §5
        """
        movement = StockMovementService.venta(
            product_id=self.product.id,
            branch_id=self.branch.id,
            quantity=Decimal("5"),
            user=self.admin,
        )
        reversal = StockMovementService.revertir(movement_id=movement.id, user=self.admin)

        with pytest.raises(InvalidMovementError, match="cannot themselves be reversed"):
            StockMovementService.revertir(movement_id=reversal.id, user=self.admin)

    def test_reversal_original_movement_is_unchanged(self):
        """
        The original movement record must never be modified.
        BUSINESS_RULES §5: movements are immutable.
        """
        from apps.movements.models import StockMovement
        movement = StockMovementService.venta(
            product_id=self.product.id,
            branch_id=self.branch.id,
            quantity=Decimal("5"),
            user=self.admin,
        )
        original_type     = movement.movement_type
        original_status   = movement.status
        original_quantity = movement.quantity

        StockMovementService.revertir(movement_id=movement.id, user=self.admin)

        movement.refresh_from_db()
        assert movement.movement_type == original_type
        assert movement.status        == original_status
        assert movement.quantity      == original_quantity

    def test_reversal_endpoint_returns_201(self, db):
        """Integration: the reversal endpoint responds with the reversal record."""
        from rest_framework.test import APIClient
        movement = StockMovementService.venta(
            product_id=self.product.id,
            branch_id=self.branch.id,
            quantity=Decimal("3"),
            user=self.admin,
        )
        client = APIClient()
        client.force_authenticate(user=self.admin)

        response = client.post(f"/api/v1/movements/{movement.id}/reverse/", format="json")

        assert response.status_code == 201
        assert response.data["movement_type"] == MovementType.REVERSAL
        assert response.data["reverses_movement"] == movement.id

    def test_seller_cannot_reverse_movement(self, db):
        """BUSINESS_RULES §1.2: only admins can create reversals."""
        from rest_framework.test import APIClient
        from tests.factories import SellerFactory
        movement = StockMovementService.venta(
            product_id=self.product.id,
            branch_id=self.branch.id,
            quantity=Decimal("3"),
            user=self.admin,
        )
        seller = SellerFactory(branch=self.branch)
        client = APIClient()
        client.force_authenticate(user=seller)

        response = client.post(f"/api/v1/movements/{movement.id}/reverse/", format="json")

        assert response.status_code == 403
