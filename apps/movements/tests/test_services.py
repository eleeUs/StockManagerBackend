"""
Tests for the StockMovementService layer.

Run with:  pytest apps/movements/tests/test_services.py -v

These tests cover:
1. Happy path for each movement type
2. Business rule enforcement (insufficient stock, same branch transfer, etc.)
3. Concurrency: two simultaneous sales must not produce negative stock
4. Transfer two-step flow: create → confirm / cancel
"""
import threading
from decimal import Decimal

import pytest
from django.test import TestCase, TransactionTestCase

from tests.factories import (
    AdminFactory,
    BranchFactory,
    ProductFactory,
    StockFactory,
)
from apps.movements.models import StockMovement, MovementStatus, MovementType
from apps.movements.services import StockMovementService
from apps.stock.models import Stock
from core.exceptions import (
    InsufficientStockError,
    InvalidMovementError,
    TransferAlreadyConfirmedError,
)


# ---------------------------------------------------------------------------
# Ingreso
# ---------------------------------------------------------------------------

class TestIngreso(TestCase):

    def setUp(self):
        self.admin   = AdminFactory()
        self.branch  = BranchFactory()
        self.product = ProductFactory()

    def test_ingreso_creates_stock_row_if_not_exists(self):
        movement = StockMovementService.ingreso(
            product_id=self.product.id,
            branch_id=self.branch.id,
            quantity=Decimal("10"),
            entry_date="2026-01-01",
            user=self.admin,
        )
        stock = Stock.objects.get(product=self.product, branch=self.branch)
        assert stock.quantity == Decimal("10")
        assert movement.movement_type == MovementType.INGRESO
        assert movement.status == MovementStatus.CONFIRMED

    def test_ingreso_adds_to_existing_stock(self):
        make_stock(self.product, self.branch, Decimal("5"))
        StockMovementService.ingreso(
            product_id=self.product.id,
            branch_id=self.branch.id,
            quantity=Decimal("10"),
            entry_date="2026-01-01",
            user=self.admin,
        )
        stock = Stock.objects.get(product=self.product, branch=self.branch)
        assert stock.quantity == Decimal("15")

    def test_ingreso_zero_quantity_raises(self):
        with pytest.raises(InvalidMovementError):
            StockMovementService.ingreso(
                product_id=self.product.id,
                branch_id=self.branch.id,
                quantity=Decimal("0"),
                entry_date="2026-01-01",
                user=self.admin,
            )


# ---------------------------------------------------------------------------
# Venta
# ---------------------------------------------------------------------------

class TestVenta(TestCase):

    def setUp(self):
        self.admin   = AdminFactory()
        self.branch  = BranchFactory()
        self.product = ProductFactory()
        StockFactory(product=self.product, branch=self.branch, quantity=Decimal("10"))

    def test_venta_decrements_stock(self):
        StockMovementService.venta(
            product_id=self.product.id,
            branch_id=self.branch.id,
            quantity=Decimal("3"),
            user=self.admin,
        )
        stock = Stock.objects.get(product=self.product, branch=self.branch)
        assert stock.quantity == Decimal("7")

    def test_venta_insufficient_stock_raises(self):
        with pytest.raises(InsufficientStockError):
            StockMovementService.venta(
                product_id=self.product.id,
                branch_id=self.branch.id,
                quantity=Decimal("999"),
                user=self.admin,
            )

    def test_venta_exact_stock_succeeds(self):
        """Edge case: selling exactly what is in stock should work."""
        StockMovementService.venta(
            product_id=self.product.id,
            branch_id=self.branch.id,
            quantity=Decimal("10"),
            user=self.admin,
        )
        stock = Stock.objects.get(product=self.product, branch=self.branch)
        assert stock.quantity == Decimal("0")

    def test_venta_stock_never_goes_negative(self):
        """
        Selling 1 more than available must raise, not store negative stock.
        """
        with pytest.raises(InsufficientStockError):
            StockMovementService.venta(
                product_id=self.product.id,
                branch_id=self.branch.id,
                quantity=Decimal("10.001"),
                user=self.admin,
            )
        stock = Stock.objects.get(product=self.product, branch=self.branch)
        assert stock.quantity == Decimal("10")  # unchanged


# ---------------------------------------------------------------------------
# Transferencia
# ---------------------------------------------------------------------------

class TestTransferencia(TestCase):

    def setUp(self):
        self.admin    = AdminFactory()
        self.branch_a = BranchFactory()
        self.branch_b = BranchFactory()
        self.product  = ProductFactory()
        StockFactory(product=self.product, branch=self.branch_a, quantity=Decimal("20"))

    def test_crear_transferencia_reserves_source_stock(self):
        movement = StockMovementService.crear_transferencia(
            product_id=self.product.id,
            source_branch_id=self.branch_a.id,
            destination_branch_id=self.branch_b.id,
            quantity=Decimal("8"),
            user=self.admin,
        )
        assert movement.status == MovementStatus.PENDING
        source = Stock.objects.get(product=self.product, branch=self.branch_a)
        assert source.quantity == Decimal("12")  # 20 - 8

    def test_confirmar_transferencia_adds_to_destination(self):
        movement = StockMovementService.crear_transferencia(
            product_id=self.product.id,
            source_branch_id=self.branch_a.id,
            destination_branch_id=self.branch_b.id,
            quantity=Decimal("8"),
            user=self.admin,
        )
        StockMovementService.confirmar_transferencia(
            movement_id=movement.id, user=self.admin
        )
        dest = Stock.objects.get(product=self.product, branch=self.branch_b)
        assert dest.quantity == Decimal("8")
        movement.refresh_from_db()
        assert movement.status == MovementStatus.CONFIRMED

    def test_cancelar_transferencia_restores_source_stock(self):
        movement = StockMovementService.crear_transferencia(
            product_id=self.product.id,
            source_branch_id=self.branch_a.id,
            destination_branch_id=self.branch_b.id,
            quantity=Decimal("8"),
            user=self.admin,
        )
        StockMovementService.cancelar_transferencia(
            movement_id=movement.id, user=self.admin
        )
        source = Stock.objects.get(product=self.product, branch=self.branch_a)
        assert source.quantity == Decimal("20")  # fully restored
        movement.refresh_from_db()
        assert movement.status == MovementStatus.CANCELLED

    def test_cancel_confirmed_transfer_raises(self):
        movement = StockMovementService.crear_transferencia(
            product_id=self.product.id,
            source_branch_id=self.branch_a.id,
            destination_branch_id=self.branch_b.id,
            quantity=Decimal("5"),
            user=self.admin,
        )
        StockMovementService.confirmar_transferencia(movement_id=movement.id, user=self.admin)
        with pytest.raises(TransferAlreadyConfirmedError):
            StockMovementService.cancelar_transferencia(movement_id=movement.id, user=self.admin)

    def test_same_branch_transfer_raises(self):
        with pytest.raises(InvalidMovementError):
            StockMovementService.crear_transferencia(
                product_id=self.product.id,
                source_branch_id=self.branch_a.id,
                destination_branch_id=self.branch_a.id,
                quantity=Decimal("5"),
                user=self.admin,
            )


# ---------------------------------------------------------------------------
# Ajuste
# ---------------------------------------------------------------------------

class TestAjuste(TestCase):

    def setUp(self):
        self.admin   = AdminFactory()
        self.branch  = BranchFactory()
        self.product = ProductFactory()
        StockFactory(product=self.product, branch=self.branch, quantity=Decimal("10"))

    def test_ajuste_sets_absolute_quantity(self):
        movement = StockMovementService.ajuste(
            product_id=self.product.id,
            branch_id=self.branch.id,
            new_quantity=Decimal("25"),
            user=self.admin,
            notes="Physical count correction",
        )
        stock = Stock.objects.get(product=self.product, branch=self.branch)
        assert stock.quantity == Decimal("25")
        assert movement.adjustment_previous_quantity == Decimal("10")

    def test_ajuste_to_zero_allowed(self):
        StockMovementService.ajuste(
            product_id=self.product.id,
            branch_id=self.branch.id,
            new_quantity=Decimal("0"),
            user=self.admin,
            notes="Write-off",
        )
        stock = Stock.objects.get(product=self.product, branch=self.branch)
        assert stock.quantity == Decimal("0")

    def test_ajuste_negative_raises(self):
        with pytest.raises(InvalidMovementError):
            StockMovementService.ajuste(
                product_id=self.product.id,
                branch_id=self.branch.id,
                new_quantity=Decimal("-1"),
                user=self.admin,
            )

    def test_ajuste_same_quantity_raises(self):
        with pytest.raises(InvalidMovementError):
            StockMovementService.ajuste(
                product_id=self.product.id,
                branch_id=self.branch.id,
                new_quantity=Decimal("10"),  # same as current
                user=self.admin,
            )


# ---------------------------------------------------------------------------
# Concurrency tests (TransactionTestCase required — wraps each test
# in a real transaction, not a savepoint, so threads can commit)
# ---------------------------------------------------------------------------

class TestConcurrentVenta(TransactionTestCase):
    """
    Two simultaneous sales for stock=1 must result in exactly one success
    and one InsufficientStockError. Stock must never go negative.
    """

    def setUp(self):
        self.admin   = AdminFactory()
        self.branch  = BranchFactory()
        self.product = ProductFactory(sku="CONC001")
        StockFactory(product=self.product, branch=self.branch, quantity=Decimal("1"))

    def test_concurrent_sales_dont_go_negative(self):
        results = []
        errors  = []

        def attempt_sale():
            try:
                StockMovementService.venta(
                    product_id=self.product.id,
                    branch_id=self.branch.id,
                    quantity=Decimal("1"),
                    user=self.admin,
                )
                results.append("success")
            except InsufficientStockError:
                errors.append("insufficient")

        threads = [threading.Thread(target=attempt_sale) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly one sale must succeed
        assert len(results) == 1, f"Expected 1 success, got {results}"
        assert len(errors)  == 1, f"Expected 1 error, got {errors}"

        # Stock must be exactly 0, never negative
        stock = Stock.objects.get(product=self.product, branch=self.branch)
        assert stock.quantity == Decimal("0"), f"Stock is {stock.quantity}"


class TestConcurrentTransfer(TransactionTestCase):
    """
    Cross-transfers A→B and B→A simultaneously should not deadlock.
    Both should complete successfully.
    """

    def setUp(self):
        self.admin    = AdminFactory()
        self.branch_a = BranchFactory()
        self.branch_b = BranchFactory()
        self.product  = ProductFactory(sku="XFER001")
        StockFactory(product=self.product, branch=self.branch_a, quantity=Decimal("10"))
        StockFactory(product=self.product, branch=self.branch_b, quantity=Decimal("10"))

    def test_cross_transfers_no_deadlock(self):
        errors = []

        def transfer_a_to_b():
            try:
                StockMovementService.crear_transferencia(
                    product_id=self.product.id,
                    source_branch_id=self.branch_a.id,
                    destination_branch_id=self.branch_b.id,
                    quantity=Decimal("3"),
                    user=self.admin,
                )
            except Exception as e:
                errors.append(str(e))

        def transfer_b_to_a():
            try:
                StockMovementService.crear_transferencia(
                    product_id=self.product.id,
                    source_branch_id=self.branch_b.id,
                    destination_branch_id=self.branch_a.id,
                    quantity=Decimal("3"),
                    user=self.admin,
                )
            except Exception as e:
                errors.append(str(e))

        t1 = threading.Thread(target=transfer_a_to_b)
        t2 = threading.Thread(target=transfer_b_to_a)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"Unexpected errors in concurrent transfers: {errors}"

        # Both transfers are pending — combined stock in both branches = 20
        stock_a = Stock.objects.get(product=self.product, branch=self.branch_a).quantity
        stock_b = Stock.objects.get(product=self.product, branch=self.branch_b).quantity
        assert stock_a + stock_b == Decimal("14")  # 20 - 3 - 3 (both sources decremented)
