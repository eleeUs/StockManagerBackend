from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator


class MovementType(models.TextChoices):
    INGRESO       = "ingreso",       "Entry"
    VENTA         = "venta",         "Sale"
    TRANSFERENCIA = "transferencia", "Transfer"
    AJUSTE        = "ajuste",        "Adjustment"
    DEVOLUCION    = "devolucion",    "Return"
    DONACION      = "donacion",      "Donation"
    # Created exclusively by the reversal service.
    # Never sent directly by a client — enforced at the view level.
    REVERSAL      = "reversal",      "Reversal"


class MovementStatus(models.TextChoices):
    CONFIRMED = "confirmed", "Confirmed"
    PENDING   = "pending",   "Pending"
    CANCELLED = "cancelled", "Cancelled"


class StockMovement(models.Model):
    """
    Append-only ledger of every stock change in the system.

    Design decisions:
    - Records are NEVER edited or deleted. If a confirmed movement must be
      corrected, a new reversal movement is created referencing the original
      via reverses_movement (BUSINESS_RULES §5).
    - Pending transfers CAN be cancelled. Cancellation updates only the
      status field and restores source stock — it does not delete the record.
    - quantity always stores a positive value (the magnitude of the movement).
      The stock effect (add vs subtract) is determined by movement_type and
      which branch field is populated.
    - For AJUSTE movements specifically:
        * quantity = the NEW absolute stock value the admin wants to set.
        * adjustment_previous_quantity = the stock value before the adjustment.
        This lets the audit trail show "was X, set to Y".
    - entry_date is only populated for INGRESO movements (formal entry date
      required by business rules §3.1). All other movement timestamps are
      captured by created_at.
    - source_branch and destination_branch are nullable because not all
      movement types have both. The service validates which combination is
      valid for each type.

    Source / destination matrix:
      INGRESO       → source=None,    destination=branch
      VENTA         → source=branch,  destination=None
      TRANSFERENCIA → source=branch,  destination=branch
      AJUSTE        → source=None,    destination=branch  (the adjusted branch)
      DEVOLUCION    → source=None,    destination=branch  (original sale branch)
      DONACION      → source=branch,  destination=None
    """

    movement_type = models.CharField(
        max_length=15,
        choices=MovementType.choices,
    )
    status = models.CharField(
        max_length=10,
        choices=MovementStatus.choices,
        default=MovementStatus.CONFIRMED,
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="movements",
    )

    # Nullable: not all movement types use both branches
    source_branch = models.ForeignKey(
        "branches.Branch",
        null=True, blank=True,
        on_delete=models.PROTECT,
        related_name="outgoing_movements",
    )
    destination_branch = models.ForeignKey(
        "branches.Branch",
        null=True, blank=True,
        on_delete=models.PROTECT,
        related_name="incoming_movements",
    )

    # Populated only for INGRESO movements. Optional even then — not every
    # entry has a formal supplier on file. Enforced at the DB level via
    # movement_supplier_only_for_ingreso: any other movement type storing
    # a supplier is a bug, not a valid state (BUSINESS_RULES §10).
    supplier = models.ForeignKey(
        "suppliers.Supplier",
        null=True, blank=True,
        on_delete=models.PROTECT,
        related_name="movements",
    )

    # Always positive — the magnitude of this movement
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )

    # Populated only for AJUSTE movements — captures the stock value
    # before the adjustment for full audit visibility.
    adjustment_previous_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True, blank=True,
    )

    # Populated only for INGRESO movements (BUSINESS_RULES §3.1).
    # Formal date of the physical stock entry, which may differ from
    # the date the record was created in the system.
    entry_date = models.DateField(null=True, blank=True)

    notes = models.TextField(blank=True)

    # If this movement reverses a previous confirmed movement,
    # this FK points to the original (BUSINESS_RULES §5).
    reverses_movement = models.OneToOneField(
        "self",
        null=True, blank=True,
        on_delete=models.PROTECT,
        related_name="reversed_by",
    )

    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="movements",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Stock Movement"
        verbose_name_plural = "Stock Movements"
        ordering            = ["-created_at"]
        indexes = [
            # History filtered by product (most common for product reports)
            models.Index(
                fields=["product", "-created_at"],
                name="idx_movement_product_date",
            ),
            # History filtered by source branch (outgoing movements)
            models.Index(
                fields=["source_branch", "-created_at"],
                name="idx_movement_source_date",
            ),
            # History filtered by destination branch (incoming movements)
            models.Index(
                fields=["destination_branch", "-created_at"],
                name="idx_movement_dest_date",
            ),
            # Filter by type + date (admin reports by movement type)
            models.Index(
                fields=["movement_type", "-created_at"],
                name="idx_movement_type_date",
            ),
            # Pending transfers — small subset, queried frequently by admins
            models.Index(
                fields=["status", "movement_type"],
                name="idx_movement_status_type",
            ),
        ]
        constraints = [
            # quantity must always be stored as a positive value
            models.CheckConstraint(
                check=models.Q(quantity__gt=Decimal("0")),
                name="movement_quantity_positive",
            ),
            # Only transfers can have a pending or cancelled status
            models.CheckConstraint(
                check=(
                    models.Q(status="confirmed") |
                    models.Q(movement_type="transferencia")
                ),
                name="movement_pending_cancelled_only_for_transfers",
            ),
            # A movement cannot transfer between the same branch
            models.CheckConstraint(
                check=~models.Q(
                    source_branch=models.F("destination_branch"),
                    source_branch__isnull=False,
                    destination_branch__isnull=False,
                ),
                name="movement_source_dest_different",
            ),
            # supplier is only meaningful on an entry (ingreso) record —
            # any other movement type storing a supplier is invalid data.
            models.CheckConstraint(
                check=(
                    models.Q(supplier__isnull=True) |
                    models.Q(movement_type="ingreso")
                ),
                name="movement_supplier_only_for_ingreso",
            ),
        ]

    def __str__(self):
        return f"{self.movement_type} | {self.product} | qty={self.quantity} | {self.created_at:%Y-%m-%d}"

    @property
    def is_pending(self):
        return self.status == MovementStatus.PENDING

    @property
    def is_confirmed(self):
        return self.status == MovementStatus.CONFIRMED

    @property
    def is_cancelled(self):
        return self.status == MovementStatus.CANCELLED
