"""
movements/services.py

The service layer is the ONLY place where stock mutation logic lives.
Views, serializers, and signals must never modify stock directly.

Concurrency strategy:
- Every operation that reads then writes stock uses select_for_update()
  inside transaction.atomic(). This serializes concurrent writes to the
  same (product, branch) stock row at the database level.
- For transfers involving two branches, locks are always acquired in
  ascending branch_id order to prevent deadlocks when two transfers
  try to lock the same two branches in opposite order simultaneously.
- The DB-level CheckConstraint on Stock.quantity is the final safety net,
  but InsufficientStockError should always fire first at the app level.
"""
import logging
from decimal import Decimal

from django.db import transaction

from apps.stock.models import Stock
from apps.movements.models import StockMovement, MovementType, MovementStatus
from core.exceptions import (
    InsufficientStockError,
    InvalidMovementError,
    TransferAlreadyConfirmedError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _lock_stock(product_id, branch_id) -> Stock:
    """
    Acquire a row-level lock on the stock row for (product, branch).
    MUST be called inside transaction.atomic().

    Returns the locked Stock instance.
    Raises InvalidMovementError if no stock row exists for this combination
    (which means the product has never been stocked at this branch).
    """
    try:
        return Stock.objects.select_for_update().get(
            product_id=product_id,
            branch_id=branch_id,
        )
    except Stock.DoesNotExist:
        raise InvalidMovementError(
            "No stock record found for this product at the specified branch. "
            "A formal entry (ingreso) must be created first."
        )


def _get_or_create_and_lock_stock(product_id, branch_id) -> Stock:
    """
    Get or create the stock row, then lock it.
    Used for INGRESO and DEVOLUCION which can legitimately be the first
    movement for a (product, branch) pair.

    The get_or_create handles the race condition for first-time creation:
    Django catches the IntegrityError from a concurrent INSERT and retries
    the GET, so at most one row is ever created per (product, branch).
    The subsequent select_for_update serializes the update.
    """
    Stock.objects.get_or_create(
        product_id=product_id,
        branch_id=branch_id,
        defaults={"quantity": Decimal("0.000")},
    )
    return Stock.objects.select_for_update().get(
        product_id=product_id,
        branch_id=branch_id,
    )


def _lock_two_stocks(product_id, branch_id_a, branch_id_b):
    """
    Acquire row-level locks on two stock rows in a deterministic order
    (ascending branch_id) to prevent deadlocks.

    Scenario without ordered locking:
      T1 locks branch 1, waits for branch 2
      T2 locks branch 2, waits for branch 1  → deadlock

    Scenario with ordered locking:
      Both T1 and T2 try to lock branch 1 first → one waits, no deadlock.

    Returns (stock_a, stock_b) in the ORIGINAL order (not the lock order),
    so callers can use them by their semantic role (source, destination).
    """
    # Sort IDs to guarantee consistent lock order
    id_low, id_high = sorted([branch_id_a, branch_id_b])

    locked = {
        s.branch_id: s
        for s in Stock.objects.select_for_update().filter(
            product_id=product_id,
            branch_id__in=[id_low, id_high],
        )
    }

    stock_a = locked.get(branch_id_a)
    stock_b = locked.get(branch_id_b)

    if stock_a is None:
        raise InvalidMovementError(
            "No stock record found for this product at the source branch."
        )
    if stock_b is None:
        # Destination may not have stock yet — create it then re-lock
        Stock.objects.get_or_create(
            product_id=product_id,
            branch_id=branch_id_b,
            defaults={"quantity": Decimal("0.000")},
        )
        # Re-acquire both locks after creation (consistent order preserved)
        locked = {
            s.branch_id: s
            for s in Stock.objects.select_for_update().filter(
                product_id=product_id,
                branch_id__in=[id_low, id_high],
            )
        }
        stock_a = locked[branch_id_a]
        stock_b = locked[branch_id_b]

    return stock_a, stock_b


# ---------------------------------------------------------------------------
# Public service methods
# ---------------------------------------------------------------------------

class StockMovementService:
    """
    All methods are @classmethod to allow easy mocking in tests
    without requiring instantiation.
    """

    @classmethod
    def ingreso(
        cls,
        *,
        product_id: int,
        branch_id: int,
        quantity: Decimal,
        entry_date,
        user,
        notes: str = "",
    ) -> StockMovement:
        """
        INGRESO — Adds stock to a branch.
        Allowed: Admin only (enforced at the view level).
        Stock effect: +quantity at destination branch.
        Creates the stock row if it does not yet exist.
        """
        if quantity <= 0:
            raise InvalidMovementError("Quantity must be greater than zero.")

        with transaction.atomic():
            stock = _get_or_create_and_lock_stock(product_id, branch_id)
            stock.quantity += quantity
            stock.save(update_fields=["quantity", "updated_at"])

            movement = StockMovement.objects.create(
                movement_type=MovementType.INGRESO,
                status=MovementStatus.CONFIRMED,
                product_id=product_id,
                destination_branch_id=branch_id,
                quantity=quantity,
                entry_date=entry_date,
                created_by=user,
                notes=notes,
            )

        logger.info(
            "INGRESO: product=%s branch=%s qty=%s by=%s",
            product_id, branch_id, quantity, user.email,
        )
        return movement

    @classmethod
    def venta(
        cls,
        *,
        product_id: int,
        branch_id: int,
        quantity: Decimal,
        user,
        notes: str = "",
    ) -> StockMovement:
        """
        VENTA — Sells stock from a branch.
        Allowed: Admin or Seller (seller restricted to their own branch,
                 enforced at the view level).
        Stock effect: -quantity at source branch.
        Raises InsufficientStockError if stock < quantity.
        """
        if quantity <= 0:
            raise InvalidMovementError("Quantity must be greater than zero.")

        with transaction.atomic():
            stock = _lock_stock(product_id, branch_id)

            if stock.quantity < quantity:
                raise InsufficientStockError(
                    f"Insufficient stock at this branch. "
                    f"Available: {stock.quantity}, requested: {quantity}."
                )

            stock.quantity -= quantity
            stock.save(update_fields=["quantity", "updated_at"])

            movement = StockMovement.objects.create(
                movement_type=MovementType.VENTA,
                status=MovementStatus.CONFIRMED,
                product_id=product_id,
                source_branch_id=branch_id,
                quantity=quantity,
                created_by=user,
                notes=notes,
            )

        logger.info(
            "VENTA: product=%s branch=%s qty=%s by=%s",
            product_id, branch_id, quantity, user.email,
        )
        return movement

    @classmethod
    def crear_transferencia(
        cls,
        *,
        product_id: int,
        source_branch_id: int,
        destination_branch_id: int,
        quantity: Decimal,
        user,
        notes: str = "",
    ) -> StockMovement:
        """
        TRANSFERENCIA (step 1 of 2) — Creates a pending transfer.
        Allowed: Admin only.

        Stock effect on creation:
          -quantity at source branch immediately (reserved).
          +quantity at destination branch ONLY on confirmation.

        The source stock is decremented on creation so it cannot be
        sold or moved by other operations while the transfer is pending.
        (BUSINESS_RULES §3.3)
        """
        if quantity <= 0:
            raise InvalidMovementError("Quantity must be greater than zero.")
        if source_branch_id == destination_branch_id:
            raise InvalidMovementError(
                "Source and destination branches must be different."
            )

        with transaction.atomic():
            # Lock source only on creation — destination is locked on confirmation
            source_stock = _lock_stock(product_id, source_branch_id)

            if source_stock.quantity < quantity:
                raise InsufficientStockError(
                    f"Insufficient stock at source branch. "
                    f"Available: {source_stock.quantity}, requested: {quantity}."
                )

            # Decrement source immediately — quantity is "in transit"
            source_stock.quantity -= quantity
            source_stock.save(update_fields=["quantity", "updated_at"])

            movement = StockMovement.objects.create(
                movement_type=MovementType.TRANSFERENCIA,
                status=MovementStatus.PENDING,
                product_id=product_id,
                source_branch_id=source_branch_id,
                destination_branch_id=destination_branch_id,
                quantity=quantity,
                created_by=user,
                notes=notes,
            )

        logger.info(
            "TRANSFERENCIA PENDING: product=%s src=%s dst=%s qty=%s by=%s",
            product_id, source_branch_id, destination_branch_id, quantity, user.email,
        )
        return movement

    @classmethod
    def confirmar_transferencia(
        cls,
        *,
        movement_id: int,
        user,
    ) -> StockMovement:
        """
        TRANSFERENCIA (step 2 of 2) — Confirms a pending transfer.
        Allowed: Admin only.

        Stock effect: +quantity at destination branch.
        The source was already decremented on creation.
        """
        with transaction.atomic():
            # Lock the movement row itself to prevent concurrent confirmations
            try:
                movement = (
                    StockMovement.objects
                    .select_for_update()
                    .select_related("product")
                    .get(pk=movement_id, movement_type=MovementType.TRANSFERENCIA)
                )
            except StockMovement.DoesNotExist:
                raise InvalidMovementError("Transfer movement not found.")

            if movement.is_confirmed:
                raise TransferAlreadyConfirmedError(
                    "This transfer has already been confirmed."
                )
            if movement.is_cancelled:
                raise InvalidMovementError(
                    "A cancelled transfer cannot be confirmed."
                )

            # Lock and update destination stock
            dest_stock = _get_or_create_and_lock_stock(
                movement.product_id,
                movement.destination_branch_id,
            )
            dest_stock.quantity += movement.quantity
            dest_stock.save(update_fields=["quantity", "updated_at"])

            movement.status = MovementStatus.CONFIRMED
            movement.save(update_fields=["status"])

        logger.info(
            "TRANSFERENCIA CONFIRMED: movement=%s by=%s",
            movement_id, user.email,
        )
        return movement

    @classmethod
    def cancelar_transferencia(
        cls,
        *,
        movement_id: int,
        user,
    ) -> StockMovement:
        """
        TRANSFERENCIA — Cancels a pending transfer.
        Allowed: Admin only.

        Stock effect: +quantity restored to source branch.
        Cannot cancel a confirmed transfer — create a reversal instead.
        (BUSINESS_RULES §5)
        """
        with transaction.atomic():
            try:
                movement = (
                    StockMovement.objects
                    .select_for_update()
                    .get(pk=movement_id, movement_type=MovementType.TRANSFERENCIA)
                )
            except StockMovement.DoesNotExist:
                raise InvalidMovementError("Transfer movement not found.")

            if movement.is_confirmed:
                raise TransferAlreadyConfirmedError(
                    "A confirmed transfer cannot be cancelled. "
                    "Create a reversal movement instead."
                )
            if movement.is_cancelled:
                raise InvalidMovementError(
                    "This transfer is already cancelled."
                )

            # Restore source stock
            source_stock = _get_or_create_and_lock_stock(
                movement.product_id,
                movement.source_branch_id,
            )
            source_stock.quantity += movement.quantity
            source_stock.save(update_fields=["quantity", "updated_at"])

            movement.status = MovementStatus.CANCELLED
            movement.save(update_fields=["status"])

        logger.info(
            "TRANSFERENCIA CANCELLED: movement=%s by=%s",
            movement_id, user.email,
        )
        return movement

    @classmethod
    def ajuste(
        cls,
        *,
        product_id: int,
        branch_id: int,
        new_quantity: Decimal,
        user,
        notes: str = "",
    ) -> StockMovement:
        """
        AJUSTE — Sets stock at a branch to an absolute value.
        Allowed: Admin only.

        new_quantity is the target quantity after the adjustment.
        Stores adjustment_previous_quantity for full audit visibility.
        Can set stock to zero. Cannot set below zero.
        (BUSINESS_RULES §3.4)
        """
        if new_quantity < 0:
            raise InvalidMovementError(
                "Adjustment quantity cannot be negative."
            )

        with transaction.atomic():
            stock = _get_or_create_and_lock_stock(product_id, branch_id)
            previous_quantity = stock.quantity

            if new_quantity == previous_quantity:
                raise InvalidMovementError(
                    "New quantity is the same as current stock. No adjustment needed."
                )

            stock.quantity = new_quantity
            stock.save(update_fields=["quantity", "updated_at"])

            movement = StockMovement.objects.create(
                movement_type=MovementType.AJUSTE,
                status=MovementStatus.CONFIRMED,
                product_id=product_id,
                destination_branch_id=branch_id,
                # quantity stores the new absolute value for adjustments
                quantity=new_quantity if new_quantity > 0 else Decimal("0.001"),
                adjustment_previous_quantity=previous_quantity,
                created_by=user,
                notes=notes,
            )

        logger.info(
            "AJUSTE: product=%s branch=%s prev=%s new=%s by=%s",
            product_id, branch_id, previous_quantity, new_quantity, user.email,
        )
        return movement

    @classmethod
    def devolucion(
        cls,
        *,
        product_id: int,
        branch_id: int,
        quantity: Decimal,
        user,
        notes: str = "",
        original_movement_id: int = None,
    ) -> StockMovement:
        """
        DEVOLUCION — Returns stock to the branch where it was sold.
        Allowed: Admin only.

        Must go back to the same branch where the original sale occurred.
        (BUSINESS_RULES §3.5)
        """
        if quantity <= 0:
            raise InvalidMovementError("Quantity must be greater than zero.")

        original_movement = None
        if original_movement_id is not None:
            try:
                original_movement = StockMovement.objects.get(
                    pk=original_movement_id,
                    movement_type=MovementType.VENTA,
                    source_branch_id=branch_id,
                )
            except StockMovement.DoesNotExist:
                raise InvalidMovementError(
                    "Referenced movement not found, is not a sale, "
                    "or does not belong to this branch."
                )

            if quantity > original_movement.quantity:
                raise InvalidMovementError(
                    f"Return quantity ({quantity}) exceeds original sale "
                    f"quantity ({original_movement.quantity})."
                )

        with transaction.atomic():
            stock = _get_or_create_and_lock_stock(product_id, branch_id)
            stock.quantity += quantity
            stock.save(update_fields=["quantity", "updated_at"])

            movement = StockMovement.objects.create(
                movement_type=MovementType.DEVOLUCION,
                status=MovementStatus.CONFIRMED,
                product_id=product_id,
                destination_branch_id=branch_id,
                quantity=quantity,
                created_by=user,
                notes=notes,
                reverses_movement=original_movement,
            )

        logger.info(
            "DEVOLUCION: product=%s branch=%s qty=%s by=%s",
            product_id, branch_id, quantity, user.email,
        )
        return movement

    @classmethod
    def donacion(
        cls,
        *,
        product_id: int,
        branch_id: int,
        quantity: Decimal,
        user,
        notes: str = "",
    ) -> StockMovement:
        """
        DONACION — Removes stock from a branch as a donation.
        Allowed: Admin only.

        Stock effect: -quantity at source branch.
        Raises InsufficientStockError if stock < quantity.
        """
        if quantity <= 0:
            raise InvalidMovementError("Quantity must be greater than zero.")

        with transaction.atomic():
            stock = _lock_stock(product_id, branch_id)

            if stock.quantity < quantity:
                raise InsufficientStockError(
                    f"Insufficient stock at this branch. "
                    f"Available: {stock.quantity}, requested: {quantity}."
                )

            stock.quantity -= quantity
            stock.save(update_fields=["quantity", "updated_at"])

            movement = StockMovement.objects.create(
                movement_type=MovementType.DONACION,
                status=MovementStatus.CONFIRMED,
                product_id=product_id,
                source_branch_id=branch_id,
                quantity=quantity,
                created_by=user,
                notes=notes,
            )

        logger.info(
            "DONACION: product=%s branch=%s qty=%s by=%s",
            product_id, branch_id, quantity, user.email,
        )
        return movement
