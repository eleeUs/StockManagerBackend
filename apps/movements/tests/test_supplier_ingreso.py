"""
apps/movements/tests/test_supplier_ingreso.py

Covers the optional supplier FK added to INGRESO movements in Phase 7:
the service accepting supplier_id, the endpoint accepting supplier in
the request body, and the DB constraint keeping supplier off every
other movement type.
"""
from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.test import TestCase

from tests.factories import AdminFactory, BranchFactory, ProductFactory, SupplierFactory
from tests.helpers import idempotent_post
from apps.movements.models import StockMovement, MovementType, MovementStatus
from apps.movements.services import StockMovementService


class TestIngresoWithSupplier(TestCase):

    def setUp(self):
        self.admin    = AdminFactory()
        self.branch   = BranchFactory()
        self.product  = ProductFactory()
        self.supplier = SupplierFactory()

    def test_ingreso_records_supplier_when_provided(self):
        movement = StockMovementService.ingreso(
            product_id=self.product.id,
            branch_id=self.branch.id,
            quantity=Decimal("10"),
            entry_date="2026-01-01",
            user=self.admin,
            supplier_id=self.supplier.id,
        )
        assert movement.supplier_id == self.supplier.id

    def test_ingreso_without_supplier_is_still_valid(self):
        movement = StockMovementService.ingreso(
            product_id=self.product.id,
            branch_id=self.branch.id,
            quantity=Decimal("10"),
            entry_date="2026-01-01",
            user=self.admin,
        )
        assert movement.supplier_id is None


@pytest.mark.django_db
class TestSupplierConstraint:
    """movement_supplier_only_for_ingreso — supplier is invalid on any
    other movement type, enforced at the DB level."""

    def test_supplier_on_non_ingreso_movement_violates_constraint(self):
        admin    = AdminFactory()
        branch   = BranchFactory()
        product  = ProductFactory()
        supplier = SupplierFactory()

        with pytest.raises(IntegrityError):
            StockMovement.objects.create(
                movement_type=MovementType.VENTA,
                status=MovementStatus.CONFIRMED,
                product=product,
                source_branch=branch,
                quantity=Decimal("1"),
                supplier=supplier,
                created_by=admin,
            )


@pytest.mark.django_db
class TestIngresoEndpointWithSupplier:
    def test_admin_can_register_entry_with_supplier(self, admin_client):
        client, _ = admin_client
        branch   = BranchFactory()
        product  = ProductFactory()
        supplier = SupplierFactory()

        response = idempotent_post(
            client,
            "/api/v1/movements/ingreso/",
            {
                "product":    product.id,
                "branch":     branch.id,
                "quantity":   "10",
                "entry_date": "2026-01-01",
                "supplier":   supplier.id,
            },
        )

        assert response.status_code == 201
        assert response.data["supplier"] == supplier.id
        assert response.data["supplier_name"] == supplier.name

    def test_entry_without_supplier_still_succeeds(self, admin_client):
        client, _ = admin_client
        branch  = BranchFactory()
        product = ProductFactory()

        response = idempotent_post(
            client,
            "/api/v1/movements/ingreso/",
            {
                "product":    product.id,
                "branch":     branch.id,
                "quantity":   "10",
                "entry_date": "2026-01-01",
            },
        )

        assert response.status_code == 201
        assert response.data["supplier"] is None
