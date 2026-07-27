"""
conftest.py — root-level pytest fixtures available to all test modules.

Fixture naming convention:
  - *_user   → a User instance, not authenticated
  - *_client → an APIClient pre-authenticated as that user type
  - The tuple pattern (client, user, branch) keeps related objects together
    without requiring extra fixtures.
"""
import pytest
from decimal import Decimal
from rest_framework.test import APIClient

from tests.factories import (
    AdminFactory,
    SellerFactory,
    BranchFactory,
    ProductFactory,
    StockFactory,
)


# ---------------------------------------------------------------------------
# API client (unauthenticated)
# ---------------------------------------------------------------------------

@pytest.fixture
def api_client():
    """Unauthenticated API client. Use for testing 401 responses."""
    return APIClient()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_user(db):
    return AdminFactory()


@pytest.fixture
def branch(db):
    return BranchFactory()


@pytest.fixture
def seller_user(db, branch):
    return SellerFactory(branch=branch)


# ---------------------------------------------------------------------------
# Authenticated clients
# Returns (client, user) or (client, user, branch) tuples so tests can
# reference both the HTTP client and the underlying user in assertions.
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_client(db):
    """Authenticated client with admin role."""
    user   = AdminFactory()
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def seller_client(db):
    """
    Authenticated client with seller role, pre-assigned to a branch.
    Returns (client, user, branch).
    """
    branch = BranchFactory()
    user   = SellerFactory(branch=branch)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user, branch


# ---------------------------------------------------------------------------
# Common domain objects
# ---------------------------------------------------------------------------

@pytest.fixture
def product(db):
    return ProductFactory()


@pytest.fixture
def product_with_stock(db):
    """
    Returns (product, branch, stock) with 50 units pre-loaded.
    Sufficient for most movement tests without hitting InsufficientStockError.
    """
    branch  = BranchFactory()
    product = ProductFactory()
    stock   = StockFactory(product=product, branch=branch, quantity=Decimal("50"))
    return product, branch, stock


@pytest.fixture
def two_branches_with_stock(db):
    """
    Returns (product, branch_a, branch_b) with 30 units at each branch.
    Used for transfer tests.
    """
    product  = ProductFactory()
    branch_a = BranchFactory()
    branch_b = BranchFactory()
    StockFactory(product=product, branch=branch_a, quantity=Decimal("30"))
    StockFactory(product=product, branch=branch_b, quantity=Decimal("30"))
    return product, branch_a, branch_b
