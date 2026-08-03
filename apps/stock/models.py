from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator


class Stock(models.Model):
    """
    Snapshot of the current stock level for a given product at a given branch.

    Design decisions:
    - One row per (product, branch) pair — enforced by unique_together and a
      DB-level UNIQUE constraint.
    - quantity uses DecimalField to support both whole-unit products and
      weight-based products (unit_type defined on Product). The service layer
      validates that unit products always receive whole numbers.
    - The non-negativity constraint exists at BOTH the application layer
      (service raises InsufficientStockError before writing) AND the database
      layer (CheckConstraint). The DB constraint is the last line of defense
      against bugs in the service or direct DB access.
    - This table is never the source of truth for "what happened" —
      StockMovement is. This table only answers "what is available right now".
    - Rows are never deleted. A product leaving a branch results in
      quantity = 0, not a deleted row.
    """

    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="stock_levels",
    )
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="stock_levels",
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("0.000"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    # Per (product, branch) reorder threshold, not a global default —
    # demand for the same product legitimately differs by branch.
    # Null means "no alert configured for this row"; check_low_stock
    # (BUSINESS_RULES §11) only evaluates rows where this is set.
    # Updated via a dedicated endpoint/admin action, never through the
    # movement service layer — it's metadata, not a stock mutation.
    reorder_point = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Stock"
        verbose_name_plural = "Stock"
        # One row per product-branch pair — DB-level enforcement
        unique_together = [("product", "branch")]
        indexes = [
            # Queries by branch are the most frequent (seller views their branch).
            # Queries by product come second (admin checks product across branches).
            models.Index(fields=["branch", "product"], name="idx_stock_branch_product"),
            models.Index(fields=["product", "branch"], name="idx_stock_product_branch"),
        ]
        constraints = [
            # DB-level guard: quantity can never be stored as negative
            # regardless of how the row was modified.
            models.CheckConstraint(
                check=models.Q(quantity__gte=Decimal("0")),
                name="stock_quantity_non_negative",
            )
        ]

    def __str__(self):
        return f"{self.product} @ {self.branch}: {self.quantity}"
