"""
tests/factories.py

Centralized factory_boy definitions for the entire project.
All test data creation goes through these factories — never raw ORM
calls in test files except when testing the ORM itself.

Usage:
    from tests.factories import AdminFactory, SellerFactory, StockFactory

    def test_something(db):
        branch  = BranchFactory()
        seller  = SellerFactory(branch=branch)
        product = ProductFactory()
        stock   = StockFactory(product=product, branch=branch, quantity=50)
"""
import factory
from factory.django import DjangoModelFactory
from decimal import Decimal

from apps.branches.models import Branch
from apps.products.models import Category, Product
from apps.users.models import User
from apps.stock.models import Stock
from apps.movements.models import StockMovement, MovementType, MovementStatus


# ---------------------------------------------------------------------------
# Branch
# ---------------------------------------------------------------------------

class BranchFactory(DjangoModelFactory):
    name      = factory.Sequence(lambda n: f"Branch {n}")
    address   = factory.Faker("street_address")
    is_active = True

    class Meta:
        model = Branch


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------

class CategoryFactory(DjangoModelFactory):
    name = factory.Sequence(lambda n: f"Category {n}")

    class Meta:
        model = Category


class ProductFactory(DjangoModelFactory):
    sku       = factory.Sequence(lambda n: f"SKU{n:04d}")
    name      = factory.Sequence(lambda n: f"Product {n}")
    category  = factory.SubFactory(CategoryFactory)
    unit_type = "unit"
    is_active = True

    class Meta:
        model = Product


class WeightProductFactory(ProductFactory):
    """Product measured in weight units (kg/g)."""
    unit_type = "weight"


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class UserFactory(DjangoModelFactory):
    email     = factory.Sequence(lambda n: f"user{n}@test.com")
    full_name = factory.Faker("name")
    role      = User.Role.SELLER
    branch    = factory.SubFactory(BranchFactory)
    is_active = True

    class Meta:
        model = User

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        # Use set_password so the password is properly hashed
        password = kwargs.pop("password", "testpassword123")
        manager = cls._get_manager(model_class)
        user = manager.create_user(password=password, **kwargs)
        return user


class AdminFactory(UserFactory):
    """Admin user — not tied to any branch."""
    role   = User.Role.ADMIN
    branch = None


class SellerFactory(UserFactory):
    """Seller user — always has a branch."""
    role   = User.Role.SELLER
    branch = factory.SubFactory(BranchFactory)


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------

class StockFactory(DjangoModelFactory):
    product  = factory.SubFactory(ProductFactory)
    branch   = factory.SubFactory(BranchFactory)
    quantity = Decimal("100.000")

    class Meta:
        model = Stock


# ---------------------------------------------------------------------------
# StockMovement
# Use only for READ tests (history, filtering, pagination).
# For WRITE tests, always go through StockMovementService
# so the Stock snapshot stays in sync.
# ---------------------------------------------------------------------------

class StockMovementFactory(DjangoModelFactory):
    movement_type      = MovementType.VENTA
    status             = MovementStatus.CONFIRMED
    product            = factory.SubFactory(ProductFactory)
    source_branch      = factory.SubFactory(BranchFactory)
    destination_branch = None
    quantity           = Decimal("5.000")
    created_by         = factory.SubFactory(AdminFactory)

    class Meta:
        model = StockMovement


class PendingTransferFactory(StockMovementFactory):
    movement_type      = MovementType.TRANSFERENCIA
    status             = MovementStatus.PENDING
    source_branch      = factory.SubFactory(BranchFactory)
    destination_branch = factory.SubFactory(BranchFactory)
